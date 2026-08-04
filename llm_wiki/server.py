"""Versioned HTTP API handlers for the local control center."""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from llm_wiki.acquisition import validate_url
from llm_wiki.control import ControlState
from llm_wiki.errors import ApiError
from llm_wiki.graph import (
    build_draft_graph,
    build_semantic_graph,
    graph_delta,
    page_context,
)
from llm_wiki.jobs import AcquisitionStore, JobRunner


def capabilities_payload(control_state: ControlState) -> dict[str, Any]:
    base = control_state.base_url.rstrip("/")
    return {
        "api_version": control_state.api_version,
        "vault_id": control_state.vault_id,
        "features": {
            "acquisitions": True,
            "graph": True,
            "pages": True,
            "plugin": True,
        },
        "routes": {
            "console": f"{base}/",
            "jobs": f"{base}/#/jobs/{{id}}",
            "drafts": f"{base}/#/drafts/{{id}}",
            "reviews": f"{base}/#/reviews/{{id}}",
            "knowledge": f"{base}/#/knowledge/{{page_id}}",
            "graph": f"{base}/#/graph?focus={{page_id}}",
        },
    }


def status_summary_payload(wiki: Any, args: Any, revision: int = 0) -> dict[str, Any]:
    summary = wiki.status_summary()
    drafts = summary.get("drafts", {})
    reviews = summary.get("reviews", {})
    queue = summary.get("queue", {})
    cfg = getattr(args, "wiki_config", None)
    profile = cfg.active if cfg else None
    llm_ready = bool(getattr(args, "llm_url", None) and getattr(args, "model", None))
    return {
        "revision": revision,
        "drafts_pending": int(drafts.get("draft", 0)),
        "facts_open": int(reviews.get("open", 0)),
        "research_open": int(reviews.get("research_open", 0)),
        "jobs_failed": int(queue.get("failed", 0)),
        "jobs_pending": int(queue.get("pending", 0)),
        "model_ready": llm_ready,
        "model_label": profile.label if profile else "",
        "model_name": getattr(args, "model", "") or "",
        "config_source": str(cfg.path) if cfg and cfg.path else "",
    }


def obsidian_link(root: Any, relative_path: str) -> str:
    absolute = (root / relative_path).resolve()
    return f"obsidian://open?path={absolute.as_posix()}"


def web_link(base_url: str, route: str) -> str:
    return f"{base_url.rstrip('/')}/{route.lstrip('/')}"


def page_detail(wiki: Any, page_id: str, base_url: str) -> dict[str, Any]:
    path = wiki.wiki / f"{page_id}.md"
    if not path.is_file():
        raise ApiError("not_found", f"页面不存在：{page_id}", retryable=False)
    from llm_wiki.text import read_text

    content = read_text(path)
    ctx = page_context(wiki.wiki, page_id)
    return {
        "id": page_id,
        "content": content,
        "sources": ctx.sources,
        "backlinks": ctx.backlinks,
        "outlinks": ctx.outlinks,
        "links": {
            "web": web_link(base_url, f"#/knowledge/{page_id}"),
            "obsidian": obsidian_link(wiki.root, f"wiki/{page_id}.md"),
        },
    }


def graph_payload(wiki: Any, focus: str | None = None, hops: int = 2) -> dict[str, Any]:
    graph = build_semantic_graph(wiki.wiki)
    if not focus:
        return graph
    pages = graph.get("pages", {})
    edges = graph.get("edges", [])
    if focus not in pages:
        raise ApiError("not_found", f"图谱节点不存在：{focus}", retryable=False)
    visible = {focus}
    frontier = {focus}
    for _ in range(max(1, min(hops, 3))):
        nxt: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src, dst = str(edge.get("from", "")), str(edge.get("to", ""))
            if src in frontier:
                nxt.add(dst)
            if dst in frontier:
                nxt.add(src)
        visible |= nxt
        frontier = nxt
    filtered_edges = [e for e in edges if isinstance(e, dict) and e.get("from") in visible and e.get("to") in visible]
    filtered_pages = {pid: pages[pid] for pid in visible if pid in pages}
    return {"pages": filtered_pages, "edges": filtered_edges, "focus": focus}


def draft_graph_delta_payload(wiki: Any, draft_id: str) -> dict[str, Any]:
    if not wiki.draft_manifest_path(draft_id).is_file():
        raise ApiError("not_found", f"草稿不存在：{draft_id}", retryable=False)
    wiki.load_draft(draft_id)
    before = build_semantic_graph(wiki.wiki)
    draft_files = wiki.draft_path(draft_id) / "files"
    after = build_draft_graph(wiki.wiki, draft_files)
    delta = graph_delta(before, after)
    return {"draft_id": draft_id, **delta}


def handle_v1_get(
    path: str,
    query: str,
    wiki: Any,
    args: Any,
    control_state: ControlState,
    *,
    authorised: bool,
) -> tuple[int, dict[str, Any]] | None:
    if path == "/api/capabilities":
        return HTTPStatus.OK, capabilities_payload(control_state)

    if not authorised and path.startswith("/api/v1/"):
        raise ApiError("unauthorised", "请求令牌无效。", retryable=False)

    if path == "/api/v1/health":
        return HTTPStatus.OK, {"status": "ok", "vault_id": control_state.vault_id}

    if path == "/api/v1/status/summary":
        return HTTPStatus.OK, status_summary_payload(wiki, args)

    if path == "/api/v1/config/llm":
        from llm_wiki.config import load_config

        cfg = getattr(args, "wiki_config", None) or load_config(wiki.root)
        payload = cfg.public_dict()
        payload["model_ready"] = bool(getattr(args, "llm_url", None) and getattr(args, "model", None))
        if cfg.active:
            payload["active"]["api_key_set"] = bool(getattr(args, "api_key", None) or cfg.active.resolve_api_key())
        return HTTPStatus.OK, payload

    if path == "/api/v1/health/wiki":
        broken, orphans, missing = wiki.lint()
        return HTTPStatus.OK, {
            "broken_links": broken,
            "orphan_pages": orphans,
            "missing_sources": missing,
        }

    if path == "/api/v1/pages":
        pages = []
        for section in ("sources", "concepts", "entities", "queries", "synthesis"):
            for item in wiki.directory_pages(section):
                page_id = wiki.relative_wiki_path(item)
                pages.append({"id": page_id, "title": item.stem})
        return HTTPStatus.OK, {"pages": pages}

    if path.startswith("/api/v1/pages/") and path.endswith("/context"):
        page_id = path.removeprefix("/api/v1/pages/").removesuffix("/context")
        ctx = page_context(wiki.wiki, page_id)
        return HTTPStatus.OK, {
            "id": page_id,
            "sources": ctx.sources,
            "backlinks": ctx.backlinks,
            "outlinks": ctx.outlinks,
            "links": {
                "web": web_link(control_state.base_url, f"#/knowledge/{page_id}"),
                "obsidian": obsidian_link(wiki.root, f"wiki/{page_id}.md"),
                "graph": web_link(control_state.base_url, f"#/graph?focus={page_id}"),
            },
        }

    if path.startswith("/api/v1/pages/"):
        page_id = path.removeprefix("/api/v1/pages/")
        return HTTPStatus.OK, page_detail(wiki, page_id, control_state.base_url)

    if path.startswith("/api/v1/drafts/") and path.endswith("/graph-delta"):
        draft_id = path.removeprefix("/api/v1/drafts/").removesuffix("/graph-delta")
        if not draft_id:
            raise ApiError("invalid_request", "缺少草稿 ID。", retryable=False)
        return HTTPStatus.OK, draft_graph_delta_payload(wiki, draft_id)

    if path == "/api/v1/graph":
        params = parse_qs(query)
        focus = params.get("focus", [None])[0]
        hops = int(params.get("hops", ["2"])[0] or "2")
        return HTTPStatus.OK, graph_payload(wiki, focus, hops)

    if path == "/api/v1/graph/neighborhood":
        params = parse_qs(query)
        focus = params.get("page_id", params.get("focus", [""]))[0]
        hops = int(params.get("hops", ["2"])[0] or "2")
        if not focus:
            raise ApiError("invalid_request", "缺少 page_id 参数。", retryable=False)
        return HTTPStatus.OK, graph_payload(wiki, focus, hops)

    if path == "/api/v1/acquisitions":
        store = AcquisitionStore(wiki.repository if hasattr(wiki, "repository") else _wiki_repository(wiki))
        items = [_acquisition_payload(store, item, control_state.base_url, wiki) for item in store.list_acquisitions()]
        return HTTPStatus.OK, {"acquisitions": items, "revision": len(items)}

    if path == "/api/v1/jobs":
        store = AcquisitionStore(wiki.repository if hasattr(wiki, "repository") else _wiki_repository(wiki))
        items = [_job_payload(store, item, control_state.base_url, wiki) for item in store.list_jobs()]
        return HTTPStatus.OK, {"jobs": items, "revision": len(items)}

    if path.startswith("/api/v1/jobs/") and path.count("/") == 4:
        job_id = path.removeprefix("/api/v1/jobs/")
        store = AcquisitionStore(wiki.repository if hasattr(wiki, "repository") else _wiki_repository(wiki))
        job = store.get_job(job_id)
        if not job:
            raise ApiError("not_found", f"任务不存在：{job_id}", retryable=False)
        return HTTPStatus.OK, _job_payload(store, job, control_state.base_url, wiki)

    return None


def _wiki_repository(wiki: Any) -> Any:
    from llm_wiki.repository import Repository

    return Repository(wiki.root)


def _resource_links(base_url: str, wiki: Any, *, web_route: str, relative_path: str = "") -> dict[str, str]:
    links: dict[str, str] = {"web": web_link(base_url, web_route)}
    if relative_path:
        links["obsidian"] = obsidian_link(wiki.root, relative_path)
    return links


def _job_payload(store: AcquisitionStore, job: dict[str, Any], base_url: str, wiki: Any) -> dict[str, Any]:
    snapshot_id = str(job.get("snapshot_id", ""))
    raw_path = ""
    if snapshot_id:
        snapshot = store._find_snapshot(snapshot_id)
        if snapshot:
            raw_path = str(snapshot.get("raw_path", ""))
    payload = dict(job)
    payload["links"] = _resource_links(
        base_url,
        wiki,
        web_route=f"#/jobs/{job.get('id', '')}",
        relative_path=raw_path,
    )
    draft_id = str(job.get("draft_id", ""))
    if draft_id:
        payload["links"]["web_draft"] = web_link(base_url, f"#/drafts/{draft_id}")
    return payload


def _acquisition_payload(store: AcquisitionStore, acquisition: dict[str, Any], base_url: str, wiki: Any) -> dict[str, Any]:
    snapshot_id = str(acquisition.get("latest_snapshot_id", ""))
    raw_path = ""
    if snapshot_id:
        snapshot = store._find_snapshot(snapshot_id)
        if snapshot:
            raw_path = str(snapshot.get("raw_path", ""))
    jobs = [job for job in store.list_jobs(limit=200) if job.get("acquisition_id") == acquisition.get("id")]
    latest_job = jobs[0] if jobs else None
    payload = dict(acquisition)
    payload["latest_job"] = latest_job
    payload["links"] = _resource_links(
        base_url,
        wiki,
        web_route=f"#/jobs/{latest_job['id']}" if latest_job else "#/jobs",
        relative_path=raw_path,
    )
    return payload


def handle_v1_post(
    path: str,
    body: bytes,
    headers: dict[str, str],
    wiki: Any,
    args: Any,
    control_state: ControlState,
    job_runner: JobRunner,
) -> tuple[int, dict[str, Any]] | None:
    store = AcquisitionStore(wiki.repository if hasattr(wiki, "repository") else _wiki_repository(wiki))
    idempotency_key = headers.get("Idempotency-Key") or headers.get("idempotency-key") or None

    if path == "/api/v1/acquisitions/url":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as error:
            raise ApiError("invalid_request", "请求 JSON 无效。", retryable=False) from error
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "请求格式无效。", retryable=False)
        url = str(payload.get("url", "")).strip()
        if not url:
            raise ApiError("invalid_request", "缺少 url 字段。", retryable=False)
        try:
            validate_url(url)
        except ValueError as error:
            code = str(error.args[0]) if error.args else "invalid_url"
            raise ApiError(code, f"URL 无效：{code}", retryable=False) from error
        job = store.create_url_acquisition(url, idempotency_key=idempotency_key)
        job_runner.notify()
        return HTTPStatus.ACCEPTED, {
            "job_id": job["id"],
            "acquisition_id": job.get("acquisition_id"),
            "links": _resource_links(control_state.base_url, wiki, web_route=f"#/jobs/{job['id']}"),
        }

    if path == "/api/v1/acquisitions/paste":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as error:
            raise ApiError("invalid_request", "请求 JSON 无效。", retryable=False) from error
        if not isinstance(payload, dict):
            raise ApiError("invalid_request", "请求格式无效。", retryable=False)
        title = str(payload.get("title", "")).strip()
        text = str(payload.get("body", payload.get("text", ""))).strip()
        source_url = str(payload.get("source_url", payload.get("url", ""))).strip()
        if not title or not text:
            raise ApiError("invalid_request", "缺少 title 或 body。", retryable=False)
        job = store.create_paste_acquisition(title, source_url=source_url, idempotency_key=idempotency_key)
        job_runner.register_paste_payload(job["id"], title=title, body=text, source_url=source_url)
        return HTTPStatus.ACCEPTED, {
            "job_id": job["id"],
            "acquisition_id": job.get("acquisition_id"),
            "links": _resource_links(control_state.base_url, wiki, web_route=f"#/jobs/{job['id']}"),
        }

    if path == "/api/v1/acquisitions/file":
        from pathlib import Path
        from urllib.parse import unquote

        from llm_wiki.jobs import SOURCE_EXTENSIONS

        raw_name = unquote(headers.get("X-Filename", ""))
        filename = Path(raw_name).name
        if not filename or Path(filename).suffix.lower() not in SOURCE_EXTENSIONS:
            raise ApiError("invalid_request", "只支持 Markdown 或 TXT 文件。", retryable=False)
        if not body or len(body) > 20 * 1024 * 1024:
            raise ApiError("invalid_request", "文件大小必须在 1 B 到 20 MB 之间。", retryable=False)
        target = wiki.inbox / filename
        target.write_bytes(body)
        job = store.create_file_acquisition(filename, idempotency_key=idempotency_key)
        job_runner.register_file_path(job["id"], target)
        return HTTPStatus.ACCEPTED, {
            "job_id": job["id"],
            "acquisition_id": job.get("acquisition_id"),
            "links": _resource_links(control_state.base_url, wiki, web_route=f"#/jobs/{job['id']}"),
        }

    if path.startswith("/api/v1/jobs/") and path.endswith("/retry"):
        job_id = path.removeprefix("/api/v1/jobs/").removesuffix("/retry")
        job = store.retry_job(job_id)
        job_runner.notify()
        return HTTPStatus.OK, _job_payload(store, job, control_state.base_url, wiki)

    return None


def api_error_response(error: ApiError) -> tuple[int, dict[str, Any]]:
    status = HTTPStatus.BAD_REQUEST
    if error.code == "unauthorised":
        status = HTTPStatus.FORBIDDEN
    elif error.code == "not_found":
        status = HTTPStatus.NOT_FOUND
    return status, error.to_dict()
