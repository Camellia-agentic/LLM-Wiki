import importlib.util
import json
import tempfile
import threading
import time
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from llm_wiki.acquisition import FetchedDocument
from llm_wiki.jobs import AcquisitionStore, JobRunner
from llm_wiki.repository import Repository

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "wiki.py"
SPEC = importlib.util.spec_from_file_location("wiki_tool", SCRIPT)
assert SPEC and SPEC.loader
wiki_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_tool)


MOCK_DOC = FetchedDocument(
    url="https://example.com/article",
    canonical_url="https://example.com/article",
    title="Article",
    text="Article body for tests.",
    content_type="text/html",
    content_digest="sha256:article-body-digest",
)


def start_acquisition_server(fetch_url_fn=None):
    root = Path(tempfile.mkdtemp()) / "vault"
    wiki = wiki_tool.Wiki(root)
    wiki.ensure_layout()
    args = Namespace(
        llm_url=None,
        model=None,
        api_key="",
        timeout=1,
        interval=1,
        settle_seconds=0,
        max_tokens=200,
        auto_accept=False,
        apply=False,
        no_watch=True,
        host="127.0.0.1",
        port=0,
    )
    control = wiki_tool.LocalControl(wiki, args)
    if fetch_url_fn is not None:
        control.job_runner.fetch_url_fn = fetch_url_fn
    server = wiki_tool.ThreadingHTTPServer(("127.0.0.1", 0), wiki_tool.make_control_handler(control))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    return base, control, server, thread, root


def api_post(base: str, token: str, path: str, payload: dict | None = None, *, idempotency_key: str = "") -> tuple[int, dict]:
    body = json.dumps(payload or {}).encode("utf-8")
    headers = {
        "X-LLM-Wiki-Token": token,
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = Request(base + path, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def api_get(base: str, token: str, path: str) -> tuple[int, dict]:
    req = Request(base + path, headers={"X-LLM-Wiki-Token": token})
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def wait_for_job(control: wiki_tool.LocalControl, job_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = control.job_store.get_job(job_id)
        if job and job.get("stage") in {"applied", "awaiting_review", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in time")


class ApiAcquisitionTests(unittest.TestCase):
    def tearDown(self) -> None:
        pass

    def test_post_url_returns_202_and_completes(self) -> None:
        base, control, server, thread, root = start_acquisition_server(fetch_url_fn=lambda _url: MOCK_DOC)
        try:
            status, data = api_post(
                base,
                control.token,
                "/api/v1/acquisitions/url",
                {"url": MOCK_DOC.url},
            )
            self.assertEqual(202, status)
            self.assertIn("job_id", data)
            self.assertIn("links", data)
            self.assertIn("web", data["links"])
            job = wait_for_job(control, data["job_id"])
            self.assertEqual("applied", job["stage"])
            self.assertTrue(list((root / "raw" / "sources").glob("*.md")))
        finally:
            control.job_runner.stop()
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_idempotency_key_reuses_job(self) -> None:
        base, control, server, thread, _root = start_acquisition_server(fetch_url_fn=lambda _url: MOCK_DOC)
        try:
            status1, data1 = api_post(
                base,
                control.token,
                "/api/v1/acquisitions/url",
                {"url": MOCK_DOC.url},
                idempotency_key="idem-1",
            )
            status2, data2 = api_post(
                base,
                control.token,
                "/api/v1/acquisitions/url",
                {"url": "https://example.com/other"},
                idempotency_key="idem-1",
            )
            self.assertEqual(202, status1)
            self.assertEqual(202, status2)
            self.assertEqual(data1["job_id"], data2["job_id"])
        finally:
            control.job_runner.stop()
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_get_jobs_and_acquisitions(self) -> None:
        base, control, server, thread, _root = start_acquisition_server(fetch_url_fn=lambda _url: MOCK_DOC)
        try:
            api_post(base, control.token, "/api/v1/acquisitions/paste", {"title": "T", "body": "B"})
            _, jobs = api_get(base, control.token, "/api/v1/jobs")
            _, acquisitions = api_get(base, control.token, "/api/v1/acquisitions")
            self.assertGreaterEqual(len(jobs["jobs"]), 1)
            self.assertGreaterEqual(len(acquisitions["acquisitions"]), 1)
            job_id = jobs["jobs"][0]["id"]
            _, detail = api_get(base, control.token, f"/api/v1/jobs/{job_id}")
            self.assertEqual(job_id, detail["id"])
            self.assertIn("links", detail)
        finally:
            control.job_runner.stop()
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_post_file_acquisition(self) -> None:
        base, control, server, thread, root = start_acquisition_server()
        try:
            body = b"# File Title\n\nBody\n"
            req = Request(
                base + "/api/v1/acquisitions/file",
                data=body,
                headers={
                    "X-LLM-Wiki-Token": control.token,
                    "X-Filename": "upload.md",
                    "Content-Type": "application/octet-stream",
                },
                method="POST",
            )
            with urlopen(req, timeout=5) as resp:
                self.assertEqual(202, resp.status)
                data = json.loads(resp.read().decode("utf-8"))
            job = wait_for_job(control, data["job_id"])
            self.assertEqual("applied", job["stage"])
            self.assertTrue(list((root / "raw" / "sources").glob("*.md")))
        finally:
            control.job_runner.stop()
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_private_url_rejected(self) -> None:
        base, control, server, thread, _root = start_acquisition_server()
        try:
            with self.assertRaises(HTTPError) as ctx:
                api_post(base, control.token, "/api/v1/acquisitions/url", {"url": "http://127.0.0.1/admin"})
            self.assertEqual(400, ctx.exception.code)
        finally:
            control.job_runner.stop()
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
