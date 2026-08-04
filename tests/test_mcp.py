import importlib.util
import json
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from llm_wiki.mcp_server import (
    FORBIDDEN_TOOLS,
    ApiProxy,
    McpJsonRpc,
    TOOL_DEFINITIONS,
    call_tool,
    load_control,
)

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
    return root, base, control.token, server, thread, control


class McpServerTests(unittest.TestCase):
    def test_tool_definitions_exclude_destructive(self) -> None:
        names = {tool["name"] for tool in TOOL_DEFINITIONS}
        self.assertIn("status_summary", names)
        self.assertIn("search", names)
        self.assertIn("list_drafts", names)
        self.assertIn("list_acquisitions", names)
        self.assertFalse(names & FORBIDDEN_TOOLS)

    def test_call_tool_status_summary(self) -> None:
        root, base, token, server, thread, control = start_test_server()
        try:
            control.control_state.base_url = base
            control.control_state.save()
            proxy = ApiProxy(root)
            result = call_tool(proxy, "status_summary", {})
            self.assertFalse(result["isError"])
            payload = json.loads(result["content"][0]["text"])
            self.assertIn("drafts_pending", payload)
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_call_tool_search_requires_query(self) -> None:
        root, base, token, server, thread, control = start_test_server()
        try:
            control.control_state.base_url = base
            control.control_state.save()
            proxy = ApiProxy(root)
            with self.assertRaises(ValueError):
                call_tool(proxy, "search", {})
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_forbidden_tool_rejected(self) -> None:
        root, base, token, server, thread, control = start_test_server()
        try:
            control.control_state.base_url = base
            control.control_state.save()
            proxy = ApiProxy(root)
            with self.assertRaises(ValueError):
                call_tool(proxy, "apply_draft", {"id": "x"})
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_jsonrpc_tools_list(self) -> None:
        root, base, token, server, thread, control = start_test_server()
        try:
            control.control_state.base_url = base
            control.control_state.save()
            rpc = McpJsonRpc(ApiProxy(root))
            response = rpc.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            assert response is not None
            self.assertEqual(1, response["id"])
            self.assertEqual(len(TOOL_DEFINITIONS), len(response["result"]["tools"]))
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_http_mcp_endpoint(self) -> None:
        root, base, token, server, thread, control = start_test_server()
        try:
            control.control_state.base_url = base
            control.control_state.save()
            from llm_wiki.mcp_server import _make_http_handler
            from http.server import ThreadingHTTPServer as McpHTTPServer

            handler = _make_http_handler(ApiProxy(root))
            mcp_server = McpHTTPServer(("127.0.0.1", 0), handler)
            mcp_thread = threading.Thread(target=mcp_server.serve_forever, daemon=True)
            mcp_thread.start()
            mcp_base = f"http://127.0.0.1:{mcp_server.server_port}"

            req = Request(
                mcp_base + "/",
                data=json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(2, data["id"])
            self.assertIn("protocolVersion", data["result"])

            with urlopen(mcp_base + "/tools", timeout=3) as resp:
                tools = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(len(TOOL_DEFINITIONS), len(tools["tools"]))

            mcp_server.shutdown()
            mcp_server.server_close()
            mcp_thread.join(timeout=3)
        finally:
            server.shutdown()
            server.server_close()
            control.instance_lock.release()
            thread.join(timeout=3)

    def test_load_control_missing(self) -> None:
        root = Path(tempfile.mkdtemp()) / "empty"
        root.mkdir()
        self.assertIsNone(load_control(root))


if __name__ == "__main__":
    unittest.main()
