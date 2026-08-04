import importlib.util
import json
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "wiki.py"
SPEC = importlib.util.spec_from_file_location("wiki_tool", SCRIPT)
assert SPEC and SPEC.loader
wiki_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_tool)


def start_test_server():
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
        no_watch=True,
        host="127.0.0.1",
        port=0,
    )
    control = wiki_tool.LocalControl(wiki, args)
    server = wiki_tool.ThreadingHTTPServer(("127.0.0.1", 0), wiki_tool.make_control_handler(control))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    return base, control.token, server, thread, control


class ApiV1Tests(unittest.TestCase):
    def test_capabilities_public(self) -> None:
        base, token, server, thread, control = start_test_server()
        try:
            with urlopen(base + "/api/capabilities", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual("v1", data["api_version"])
            self.assertIn("vault_id", data)
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_health_requires_token(self) -> None:
        base, token, server, thread, control = start_test_server()
        try:
            with self.assertRaises(HTTPError):
                urlopen(base + "/api/v1/health", timeout=3)
            req = Request(base + "/api/v1/health", headers={"X-LLM-Wiki-Token": token})
            with urlopen(req, timeout=3) as resp:
                self.assertEqual(200, resp.status)
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_status_summary(self) -> None:
        base, token, server, thread, control = start_test_server()
        try:
            req = Request(base + "/api/v1/status/summary", headers={"X-LLM-Wiki-Token": token})
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("drafts_pending", data)
            self.assertIn("revision", data)
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
