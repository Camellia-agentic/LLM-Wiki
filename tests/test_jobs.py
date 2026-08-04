import importlib.util
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from llm_wiki.acquisition import FetchedDocument
from llm_wiki.jobs import AcquisitionStore, JOB_STAGES, JobRunner
from llm_wiki.repository import Repository

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "wiki.py"
SPEC = importlib.util.spec_from_file_location("wiki_tool", SCRIPT)
assert SPEC and SPEC.loader
wiki_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_tool)


def offline_args() -> Namespace:
    return Namespace(
        llm_url=None,
        model=None,
        api_key="",
        timeout=1,
        max_tokens=200,
        apply=False,
        auto_accept=False,
    )


def sample_doc(url: str = "https://example.com/doc", text: str = "Body text") -> FetchedDocument:
    digest = f"sha256:{hash(text)}"
    return FetchedDocument(
        url=url,
        canonical_url=url,
        title="Example Doc",
        text=text,
        content_type="text/html",
        content_digest=digest if digest.startswith("sha256:") else f"sha256:{digest}",
    )


class AcquisitionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "vault"
        self.wiki = wiki_tool.Wiki(self.root)
        self.wiki.ensure_layout()
        self.repo = Repository(self.root)
        self.store = AcquisitionStore(self.repo)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_url_acquisition_returns_job(self) -> None:
        job = self.store.create_url_acquisition("https://example.com/a")
        self.assertTrue(job["id"].startswith("job_"))
        self.assertEqual("queued", job["stage"])
        self.assertIn("queued", JOB_STAGES)

    def test_idempotency_key_reuses_job(self) -> None:
        first = self.store.create_url_acquisition("https://example.com/a", idempotency_key="key-1")
        second = self.store.create_url_acquisition("https://example.com/b", idempotency_key="key-1")
        self.assertEqual(first["id"], second["id"])
        state = self.repo.load_state()
        self.assertEqual(1, len(state["jobs"]))

    def test_list_jobs_and_acquisitions(self) -> None:
        self.store.create_paste_acquisition("Paste Title")
        self.assertEqual(1, len(self.store.list_acquisitions()))
        self.assertEqual(1, len(self.store.list_jobs()))

    def test_retry_failed_job(self) -> None:
        job = self.store.create_url_acquisition("https://example.com/a")
        self.store.update_job(job["id"], stage="failed", retryable=True)
        retried = self.store.retry_job(job["id"])
        self.assertEqual("queued", retried["stage"])


class JobRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "vault"
        self.wiki = wiki_tool.Wiki(self.root)
        self.wiki.ensure_layout()
        self.repo = Repository(self.root)
        self.store = AcquisitionStore(self.repo)
        self.args = offline_args()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_url_job_archives_snapshot(self) -> None:
        doc = FetchedDocument(
            url="https://example.com/doc",
            canonical_url="https://example.com/doc",
            title="Example Doc",
            text="Stable body",
            content_type="text/html",
            content_digest="sha256:abc123deadbeef",
        )
        runner = JobRunner(self.wiki, self.args, self.store, fetch_url_fn=lambda _url: doc)
        job = self.store.create_url_acquisition(doc.url)
        runner._process_job(job["id"])
        updated = self.store.get_job(job["id"])
        self.assertEqual("applied", updated["stage"])
        archived = list((self.root / "raw" / "sources").glob("*.md"))
        self.assertEqual(1, len(archived))

    def test_same_url_same_body_reuses_snapshot(self) -> None:
        doc = FetchedDocument(
            url="https://example.com/doc",
            canonical_url="https://example.com/doc",
            title="Example Doc",
            text="Stable body",
            content_type="text/html",
            content_digest="sha256:fixeddigest0001",
        )
        runner = JobRunner(self.wiki, self.args, self.store, fetch_url_fn=lambda _url: doc)
        first_job = self.store.create_url_acquisition(doc.url)
        runner._process_job(first_job["id"])
        state = self.repo.load_state()
        self.assertEqual(1, len(state["snapshots"]))
        acquisition_id = first_job["acquisition_id"]

        second_job = self.store._create_job(acquisition_id, snapshot_id=state["snapshots"][0]["id"])
        runner._process_job(second_job["id"])
        state = self.repo.load_state()
        self.assertEqual(1, len(state["snapshots"]))
        acquisition = next(item for item in state["acquisitions"] if item["id"] == acquisition_id)
        self.assertTrue(acquisition["checked_at"])

    def test_paste_job_archives_snapshot(self) -> None:
        runner = JobRunner(self.wiki, self.args, self.store)
        job = self.store.create_paste_acquisition("Paste Title")
        runner.register_paste_payload(job["id"], title="Paste Title", body="Pasted content")
        runner._process_job(job["id"])
        updated = self.store.get_job(job["id"])
        self.assertEqual("applied", updated["stage"])


if __name__ == "__main__":
    unittest.main()
