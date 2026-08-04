"""Thin MCP server forwarding read-only tools to the loopback LLM Wiki API."""

from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from llm_wiki.control import ControlState

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "llm-wiki"
SERVER_VERSION = "0.2.0"

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "status_summary",
        "description": "Vault status: pending drafts, open reviews, job counts, model readiness.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search",
        "description": "Search the Wiki index (FTS5 + BM25). Does not modify content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "limit": {"type": "integer", "description": "Max results (default 8).", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_drafts",
        "description": "List pending model drafts awaiting review. Apply/discard must use the Web console.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_acquisitions",
        "description": "List recent acquisition records and their latest jobs.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

FORBIDDEN_TOOLS = frozenset({"apply_draft", "discard_draft", "remove", "delete", "accept_draft"})


def load_control(root: Path) -> ControlState | None:
    """Load control.json without creating a new token."""
    control_path = root.resolve() / ".llm-wiki" / "control.json"
    if not control_path.is_file():
        return None
    try:
        raw = json.loads(control_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    token = str(raw.get("api_token") or raw.get("token") or "")
    if not token:
        return None
    return ControlState(
        vault_id=str(raw.get("vault_id") or ""),
        token=token,
        base_url=str(raw.get("base_url") or "http://127.0.0.1:8765").rstrip("/"),
        api_version=str(raw.get("api_version") or "v1"),
        schema_version=int(raw.get("schema_version") or 1),
        updated_at=str(raw.get("updated_at") or ""),
        root=root.resolve(),
    )


class ApiProxy:
    """Forward MCP tool calls to the existing loopback HTTP API."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def control(self) -> ControlState:
        state = load_control(self.root)
        if state is None:
            raise RuntimeError(
                "control.json not found. Start the service first: python tools/wiki.py serve"
            )
        return state

    def _request(self, method: str, path: str, *, body: bytes | None = None) -> Any:
        state = self.control()
        headers = {"X-LLM-Wiki-Token": state.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{state.base_url}{path}"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                message = parsed.get("message") or parsed.get("error") or detail
            except json.JSONDecodeError:
                message = detail or str(error)
            raise RuntimeError(f"API {error.code}: {message}") from error
        except URLError as error:
            raise RuntimeError(
                f"Cannot reach LLM Wiki at {state.base_url}. Is serve running?"
            ) from error
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))

    def status_summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/status/summary")

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        params = urlencode({"q": query})
        result = self._request("GET", f"/api/search?{params}")
        if isinstance(result, list):
            return result[:limit]
        return []

    def list_drafts(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/api/drafts")
        return result if isinstance(result, list) else []

    def list_acquisitions(self) -> dict[str, Any]:
        result = self._request("GET", "/api/v1/acquisitions")
        return result if isinstance(result, dict) else {"acquisitions": []}


def call_tool(proxy: ApiProxy, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Execute a whitelisted MCP tool and return MCP content payload."""
    if name in FORBIDDEN_TOOLS:
        raise ValueError(f"Tool {name!r} is not exposed. Use the Web console for destructive actions.")
    args = arguments or {}
    if name == "status_summary":
        data = proxy.status_summary()
    elif name == "search":
        query = str(args.get("query", "")).strip()
        if not query:
            raise ValueError("search requires a non-empty query.")
        limit = int(args.get("limit", 8) or 8)
        limit = max(1, min(limit, 50))
        data = proxy.search(query, limit)
    elif name == "list_drafts":
        data = proxy.list_drafts()
    elif name == "list_acquisitions":
        data = proxy.list_acquisitions()
    else:
        raise ValueError(f"Unknown tool: {name}")
    text = json.dumps(data, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


class McpJsonRpc:
    """Minimal MCP JSON-RPC handler (initialize, tools/list, tools/call)."""

    def __init__(self, proxy: ApiProxy):
        self.proxy = proxy
        self._initialised = False

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method", "")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if method == "notifications/initialized":
            self._initialised = True
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOL_DEFINITIONS},
            }

        if method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            try:
                result = call_tool(self.proxy, name, arguments)
            except (ValueError, RuntimeError) as error:
                result = {
                    "content": [{"type": "text", "text": str(error)}],
                    "isError": True,
                }
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        if msg_id is None:
            return None

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def read_framed_message(stream) -> dict[str, Any] | None:
    """Read one Content-Length framed JSON-RPC message from a binary stream."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            break
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or "0")
    if length <= 0:
        return None
    body = stream.read(length)
    if not body:
        return None
    parsed = json.loads(body.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else None


def write_framed_message(stream, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(header)
    stream.write(body)
    stream.flush()


def run_stdio(root: Path) -> int:
    """Run MCP over stdin/stdout (Content-Length framed JSON-RPC)."""
    proxy = ApiProxy(root)
    handler = McpJsonRpc(proxy)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        message = read_framed_message(stdin)
        if message is None:
            break
        response = handler.handle(message)
        if response is not None:
            write_framed_message(stdout, response)
    return 0


def run_http(root: Path, host: str = "127.0.0.1", port: int = 8766) -> int:
    """Run a simple loopback HTTP JSON-RPC endpoint for MCP tools."""
    proxy = ApiProxy(root)
    handler_cls = _make_http_handler(proxy)

    server = ThreadingHTTPServer((host, port), handler_cls)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


def _make_http_handler(proxy: ApiProxy) -> type[BaseHTTPRequestHandler]:
    rpc = McpJsonRpc(proxy)

    class McpHttpHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("Invalid Content-Length.")
            raw = self.rfile.read(length)
            parsed = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object.")
            return parsed

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/tools":
                self._send_json(HTTPStatus.OK, {"tools": TOOL_DEFINITIONS})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            try:
                message = self._read_json()
            except (ValueError, json.JSONDecodeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            response = rpc.handle(message)
            if response is None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            self._send_json(HTTPStatus.OK, response)

    return McpHttpHandler
