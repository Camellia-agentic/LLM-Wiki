"""Acquisition records, job stages, and background processing."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import traceback
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from llm_wiki.acquisition import FetchedDocument, create_paste_snapshot, fetch_url
from llm_wiki.errors import ApiError
from llm_wiki.repository import Repository
from llm_wiki.text import first_heading, read_text, sha256, slug, timestamp, write_text, yaml_quote

SOURCE_EXTENSIONS = {".md", ".markdown", ".txt"}

JOB_STAGES = (
    "queued",
    "acquiring",
    "archived",
    "chunking",
    "analyzing",
    "merging",
    "drafting",
    "awaiting_review",
    "applied",
    "failed",
)

TERMINAL_STAGES = frozenset({"awaiting_review", "applied", "failed"})


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _digest_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_url_snapshot_markdown(doc: FetchedDocument, *, captured_at: str | None = None) -> str:
    captured = captured_at or timestamp()
    lines = [
        "---",
        "source_kind: url",
        f"source_url: {yaml_quote(doc.url)}",
        f"canonical_url: {yaml_quote(doc.canonical_url)}",
        f'captured_at: "{captured}"',
        f'content_digest: "{doc.content_digest}"',
        f"content_type: {yaml_quote(doc.content_type)}",
        "extractor: html-main",
        'extractor_version: "1"',
        "---",
        "",
        f"# {doc.title}",
        "",
        doc.text.rstrip(),
        "",
    ]
    return "\n".join(lines)


class AcquisitionStore:
    """Persist acquisitions, snapshots, and jobs in state.json."""

    def __init__(self, repository: Repository):
        self.repository = repository
        self.idempotency_path = repository.runtime / "idempotency.json"

    def _load_idempotency(self) -> dict[str, Any]:
        if not self.idempotency_path.exists():
            return {"keys": {}}
        try:
            raw = json.loads(read_text(self.idempotency_path))
            if not isinstance(raw, dict):
                return {"keys": {}}
            raw.setdefault("keys", {})
            return raw
        except (json.JSONDecodeError, OSError):
            return {"keys": {}}

    def _save_idempotency(self, payload: dict[str, Any]) -> None:
        write_text(self.idempotency_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def resolve_idempotency(self, key: str | None) -> dict[str, Any] | None:
        if not key:
            return None
        keys = self._load_idempotency().get("keys", {})
        entry = keys.get(key)
        if not isinstance(entry, dict):
            return None
        job = self.get_job(str(entry.get("job_id", "")))
        return job

    def bind_idempotency(self, key: str | None, job_id: str) -> None:
        if not key:
            return
        payload = self._load_idempotency()
        keys = payload.setdefault("keys", {})
        keys[key] = {"job_id": job_id, "created_at": timestamp()}
        self._save_idempotency(payload)

    def _mutate_state(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        state = self.repository.load_state()
        state.setdefault("acquisitions", [])
        state.setdefault("snapshots", [])
        state.setdefault("jobs", [])
        result = mutator(state)
        self.repository.save_state(state)
        return result

    def _find_acquisition_by_origin(self, canonical_origin: str) -> dict[str, Any] | None:
        state = self.repository.load_state()
        for item in state.get("acquisitions", []):
            if isinstance(item, dict) and str(item.get("canonical_origin", "")) == canonical_origin:
                return item
        return None

    def _find_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        state = self.repository.load_state()
        for item in state.get("snapshots", []):
            if isinstance(item, dict) and str(item.get("id", "")) == snapshot_id:
                return item
        return None

    def _create_acquisition(
        self,
        *,
        kind: str,
        origin: str,
        canonical_origin: str,
        display_title: str,
    ) -> dict[str, Any]:
        now = timestamp()
        acquisition = {
            "id": _new_id("acq"),
            "kind": kind,
            "origin": origin,
            "canonical_origin": canonical_origin,
            "display_title": display_title,
            "status": "queued",
            "latest_snapshot_id": "",
            "created_at": now,
            "checked_at": now,
            "error_code": "",
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            state["acquisitions"].append(acquisition)
            return acquisition

        return self._mutate_state(mutate)

    def _create_job(self, acquisition_id: str, *, snapshot_id: str = "") -> dict[str, Any]:
        now = timestamp()
        job = {
            "id": _new_id("job"),
            "acquisition_id": acquisition_id,
            "snapshot_id": snapshot_id,
            "stage": "queued",
            "attempts": 0,
            "error_code": "",
            "error_message": "",
            "retryable": False,
            "created_at": now,
            "updated_at": now,
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            state["jobs"].append(job)
            return job

        return self._mutate_state(mutate)

    def _register_snapshot(
        self,
        acquisition_id: str,
        *,
        content_digest: str,
        raw_path: str,
        content_type: str,
        extractor: str,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        captured = captured_at or timestamp()
        snapshot = {
            "id": _new_id("snap"),
            "acquisition_id": acquisition_id,
            "content_digest": content_digest,
            "raw_path": raw_path,
            "captured_at": captured,
            "content_type": content_type,
            "etag": "",
            "last_modified": "",
            "extractor": extractor,
            "extractor_version": "1",
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            state["snapshots"].append(snapshot)
            for acquisition in state["acquisitions"]:
                if acquisition.get("id") == acquisition_id:
                    acquisition["latest_snapshot_id"] = snapshot["id"]
                    acquisition["status"] = "captured"
                    acquisition["checked_at"] = timestamp()
                    break
            return snapshot

        return self._mutate_state(mutate)

    def _touch_acquisition_checked(self, acquisition_id: str) -> None:
        def mutate(state: dict[str, Any]) -> None:
            for acquisition in state["acquisitions"]:
                if acquisition.get("id") == acquisition_id:
                    acquisition["checked_at"] = timestamp()
                    acquisition["status"] = "captured"
                    break

        self._mutate_state(mutate)

    def create_file_acquisition(
        self,
        filename: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        existing = self.resolve_idempotency(idempotency_key)
        if existing:
            return existing
        acquisition = self._create_acquisition(
            kind="file",
            origin=filename,
            canonical_origin=filename,
            display_title=Path(filename).stem,
        )
        job = self._create_job(acquisition["id"])
        self.bind_idempotency(idempotency_key, job["id"])
        return job

    def create_url_acquisition(
        self,
        url: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        existing = self.resolve_idempotency(idempotency_key)
        if existing:
            return existing
        parsed = urlparse(url.strip())
        title = parsed.path.rsplit("/", 1)[-1] or url
        acquisition = self._create_acquisition(
            kind="url",
            origin=url.strip(),
            canonical_origin=url.strip(),
            display_title=title,
        )
        job = self._create_job(acquisition["id"])
        self.bind_idempotency(idempotency_key, job["id"])
        return job

    def create_paste_acquisition(
        self,
        title: str,
        *,
        source_url: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        existing = self.resolve_idempotency(idempotency_key)
        if existing:
            return existing
        acquisition = self._create_acquisition(
            kind="paste",
            origin=title,
            canonical_origin=source_url or title,
            display_title=title,
        )
        job = self._create_job(acquisition["id"])
        self.bind_idempotency(idempotency_key, job["id"])
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        state = self.repository.load_state()
        for job in state.get("jobs", []):
            if isinstance(job, dict) and str(job.get("id", "")) == job_id:
                return dict(job)
        return None

    def get_acquisition(self, acquisition_id: str) -> dict[str, Any] | None:
        state = self.repository.load_state()
        for item in state.get("acquisitions", []):
            if isinstance(item, dict) and str(item.get("id", "")) == acquisition_id:
                return dict(item)
        return None

    def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        state = self.repository.load_state()
        jobs = [dict(item) for item in state.get("jobs", []) if isinstance(item, dict)]
        jobs.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return jobs[: max(1, min(limit, 200))]

    def list_acquisitions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        state = self.repository.load_state()
        items = [dict(item) for item in state.get("acquisitions", []) if isinstance(item, dict)]
        items.sort(key=lambda item: str(item.get("checked_at", "")), reverse=True)
        return items[: max(1, min(limit, 200))]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            for job in state["jobs"]:
                if job.get("id") == job_id:
                    job.update(fields)
                    job["updated_at"] = timestamp()
                    return dict(job)
            return None

        return self._mutate_state(mutate)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise ApiError("not_found", f"任务不存在：{job_id}", retryable=False)
        if job.get("stage") != "failed":
            raise ApiError("invalid_request", "只有失败任务可以重试。", retryable=False)
        if not job.get("retryable"):
            raise ApiError("invalid_request", "此失败不可重试。", retryable=False)
        updated = self.update_job(
            job_id,
            stage="queued",
            error_code="",
            error_message="",
            retryable=False,
        )
        if not updated:
            raise ApiError("not_found", f"任务不存在：{job_id}", retryable=False)
        return updated


class JobRunner:
    """Background worker for acquisition jobs."""

    def __init__(
        self,
        wiki: Any,
        args: Any,
        store: AcquisitionStore,
        *,
        fetch_url_fn: Callable[..., FetchedDocument] | None = None,
    ):
        self.wiki = wiki
        self.args = args
        self.store = store
        self.fetch_url_fn = fetch_url_fn or fetch_url
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._processing_lock = threading.Lock()
        self._pending_files: dict[str, Path] = {}
        self._pending_paste: dict[str, dict[str, str]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="llm-wiki-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def register_file_path(self, job_id: str, path: Path) -> None:
        self._pending_files[job_id] = path
        self._wake.set()

    def register_paste_payload(self, job_id: str, *, title: str, body: str, source_url: str = "") -> None:
        self._pending_paste[job_id] = {"title": title, "body": body, "source_url": source_url}
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def _worker(self) -> None:
        while not self._stop.is_set():
            job = self._next_job()
            if job:
                with self._processing_lock:
                    try:
                        self._process_job(job["id"])
                    except Exception as error:
                        self.store.update_job(
                            job["id"],
                            stage="failed",
                            error_code="internal_error",
                            error_message=str(error),
                            retryable=True,
                        )
            else:
                self._wake.wait(timeout=0.5)
                self._wake.clear()

    def _next_job(self) -> dict[str, Any] | None:
        for job in self.store.list_jobs(limit=200):
            if job.get("stage") == "queued":
                return job
        return None

    def _set_stage(self, job_id: str, stage: str) -> None:
        if stage not in JOB_STAGES:
            raise ValueError(f"unknown job stage: {stage}")
        self.store.update_job(job_id, stage=stage)

    def _fail_job(self, job_id: str, code: str, message: str, *, retryable: bool) -> None:
        self.store.update_job(
            job_id,
            stage="failed",
            error_code=code,
            error_message=message,
            retryable=retryable,
        )

    def _process_job(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job or job.get("stage") != "queued":
            return
        acquisition = self.store.get_acquisition(str(job.get("acquisition_id", "")))
        if not acquisition:
            self._fail_job(job_id, "missing_acquisition", "采集记录不存在。", retryable=False)
            return

        self.store.update_job(job_id, attempts=int(job.get("attempts", 0)) + 1)

        kind = str(acquisition.get("kind", ""))
        if kind == "file":
            self._process_file_job(job_id, acquisition)
        elif kind == "url":
            self._process_url_job(job_id, acquisition)
        elif kind == "paste":
            payload = self._pending_paste.pop(job_id, None)
            if not payload:
                self._fail_job(job_id, "missing_payload", "粘贴任务缺少正文。", retryable=False)
                return
            self.process_paste_job(
                job_id,
                payload["title"],
                payload["body"],
                source_url=payload.get("source_url", ""),
            )
        else:
            self._fail_job(job_id, "unsupported_kind", f"不支持的采集类型：{kind}", retryable=False)

    def process_paste_job(self, job_id: str, title: str, body: str, *, source_url: str = "") -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        acquisition = self.store.get_acquisition(str(job.get("acquisition_id", "")))
        if not acquisition:
            self._fail_job(job_id, "missing_acquisition", "采集记录不存在。", retryable=False)
            return
        self._set_stage(job_id, "acquiring")
        try:
            markdown = create_paste_snapshot(title, body, source_url=source_url)
            digest = f"sha256:{_digest_hex(body)}"
            existing = self._find_reusable_snapshot(acquisition["id"], digest)
            if existing:
                self.store.update_job(job_id, snapshot_id=existing["id"])
                self._touch_and_finish_reused(job_id, acquisition["id"], existing)
                return
            raw_path = self._write_snapshot_file(title, markdown, prefix="paste")
            snapshot = self.store._register_snapshot(
                acquisition["id"],
                content_digest=digest,
                raw_path=raw_path,
                content_type="text/markdown",
                extractor="paste",
            )
            self.store.update_job(job_id, snapshot_id=snapshot["id"])
            self._run_pipeline(job_id, title, raw_path, markdown, digest.removeprefix("sha256:"))
        except Exception as error:
            self._fail_job(job_id, "paste_failed", str(error), retryable=True)

    def _process_file_job(self, job_id: str, acquisition: dict[str, Any]) -> None:
        source_path = self._pending_files.pop(job_id, None)
        if source_path is None or not source_path.is_file():
            self._fail_job(job_id, "missing_file", "上传文件不可用。", retryable=False)
            return
        self._set_stage(job_id, "acquiring")
        try:
            self._set_stage(job_id, "archived")
            imported = self.wiki.ingest(source_path, self.args)
            digest = sha256(source_path)
            state = self.wiki.load_state()
            entry = state.get("sources", {}).get(digest, {})
            raw_path = str(entry.get("raw_path", ""))
            if raw_path:
                content = read_text(self.wiki.root / raw_path)
                content_digest = f"sha256:{_digest_hex(content)}"
                snapshot = self.store._register_snapshot(
                    acquisition["id"],
                    content_digest=content_digest,
                    raw_path=raw_path,
                    content_type="text/markdown",
                    extractor="file",
                )
                self.store.update_job(job_id, snapshot_id=snapshot["id"])
            self._finish_from_legacy_state(job_id, entry, imported)
        except Exception as error:
            self._fail_job(job_id, "ingest_failed", str(error), retryable=True)

    def _process_url_job(self, job_id: str, acquisition: dict[str, Any]) -> None:
        self._set_stage(job_id, "acquiring")
        url = str(acquisition.get("origin", ""))
        try:
            document = self.fetch_url_fn(url)
        except ValueError as error:
            code = str(error.args[0]) if error.args else "fetch_failed"
            self._fail_job(job_id, code, f"URL 抓取失败：{code}", retryable=code not in {"invalid_url", "private_network", "unsupported_scheme"})
            return
        except Exception as error:
            self._fail_job(job_id, "fetch_failed", str(error), retryable=True)
            return

        existing = self._find_reusable_snapshot(acquisition["id"], document.content_digest)
        if existing:
            self.store.update_job(job_id, snapshot_id=existing["id"])
            self._touch_and_finish_reused(job_id, acquisition["id"], existing)
            return

        markdown = create_url_snapshot_markdown(document)
        raw_path = self._write_snapshot_file(document.title or url, markdown, prefix="url")
        snapshot = self.store._register_snapshot(
            acquisition["id"],
            content_digest=document.content_digest,
            raw_path=raw_path,
            content_type=document.content_type,
            extractor="html-main",
        )
        self.store.update_job(job_id, snapshot_id=snapshot["id"])
        self._set_stage(job_id, "archived")
        digest = document.content_digest.removeprefix("sha256:")
        self._run_pipeline(job_id, document.title, raw_path, markdown, digest)

    def _find_reusable_snapshot(self, acquisition_id: str, content_digest: str) -> dict[str, Any] | None:
        state = self.store.repository.load_state()
        latest_id = ""
        for acquisition in state.get("acquisitions", []):
            if acquisition.get("id") == acquisition_id:
                latest_id = str(acquisition.get("latest_snapshot_id", ""))
                break
        if not latest_id:
            return None
        for snapshot in state.get("snapshots", []):
            if snapshot.get("id") == latest_id and snapshot.get("content_digest") == content_digest:
                return dict(snapshot)
        return None

    def _touch_and_finish_reused(self, job_id: str, acquisition_id: str, snapshot: dict[str, Any]) -> None:
        self.store._touch_acquisition_checked(acquisition_id)
        self._set_stage(job_id, "archived")
        raw_path = str(snapshot.get("raw_path", ""))
        if raw_path and (self.wiki.root / raw_path).is_file():
            content = read_text(self.wiki.root / raw_path)
            title = first_heading(content, Path(raw_path).stem)
            digest = str(snapshot.get("content_digest", "")).removeprefix("sha256:")
            self._run_pipeline(job_id, title, raw_path, content, digest)
        else:
            self._set_stage(job_id, "applied")

    def _write_snapshot_file(self, title: str, markdown: str, *, prefix: str) -> str:
        base = slug(title, prefix)
        snap_id = _digest_hex(markdown)[:10]
        target = self.wiki.raw / f"{base}-{snap_id}.md"
        if not target.exists():
            write_text(target, markdown)
        return target.relative_to(self.wiki.root).as_posix()

    def _run_pipeline(self, job_id: str, title: str, raw_path: str, content: str, digest: str) -> None:
        self._set_stage(job_id, "chunking")
        if not getattr(self.args, "llm_url", None) or not getattr(self.args, "model", None):
            self._set_stage(job_id, "applied")
            state = self.wiki.load_state()
            state.setdefault("sources", {})
            state["sources"].setdefault(
                digest,
                {
                    "raw_path": raw_path,
                    "title": title,
                    "status": "archived",
                },
            )
            self.wiki.save_state(state)
            return

        try:
            self._set_stage(job_id, "analyzing")
            generation = self.wiki.generate_from_source(title, raw_path, content, digest, self.args)
            self._set_stage(job_id, "merging")
            self._set_stage(job_id, "drafting")
        except Exception as error:
            self._fail_job(job_id, "pipeline_failed", str(error), retryable=True)
            return

        if generation and not getattr(self.args, "apply", False) and not getattr(self.args, "auto_accept", False):
            pages, source_page, duplicates = self.wiki.render_source_pages(title, raw_path, content, generation)
            manifest = self.wiki.create_draft(
                "ingest",
                title,
                pages,
                source={
                    "digest": digest,
                    "raw_path": raw_path,
                    "source_page": source_page,
                    "title": title,
                    "analysis_path": self.wiki.analysis_path(digest).relative_to(self.wiki.root).as_posix(),
                },
                review_items=generation.get("review_items", []),
                duplicate_candidates=duplicates,
            )
            state = self.wiki.load_state()
            state.setdefault("sources", {})
            state["sources"][digest] = {
                "raw_path": raw_path,
                "title": title,
                "status": "draft",
                "draft_id": manifest["id"],
                "analysis_path": self.wiki.analysis_path(digest).relative_to(self.wiki.root).as_posix(),
            }
            self.wiki.save_state(state)
            self.store.update_job(job_id, stage="awaiting_review", draft_id=manifest["id"])
            return

        page = self.wiki.write_source_page(title, raw_path, content, generation)
        self.wiki.append_reviews(title, raw_path, generation.get("review_items", []))
        self.wiki.append_log("ingest", title, f"- 原始资料：[{raw_path}](../{raw_path})\n- 摘要：[[{self.wiki.wiki_link(page)}]]")
        state = self.wiki.load_state()
        state.setdefault("sources", {})
        state["sources"][digest] = {
            "raw_path": raw_path,
            "source_page": self.wiki.relative_wiki_path(page),
            "title": title,
            "ingested_at": timestamp(),
            "status": "applied",
            "analysis_path": self.wiki.analysis_path(digest).relative_to(self.wiki.root).as_posix() if generation else "",
        }
        self.wiki.save_state(state)
        self._set_stage(job_id, "applied")

    def _finish_from_legacy_state(self, job_id: str, entry: dict[str, Any], imported: bool) -> None:
        status = str(entry.get("status", ""))
        if status == "draft":
            self.store.update_job(job_id, stage="awaiting_review", draft_id=str(entry.get("draft_id", "")))
        elif imported:
            self._set_stage(job_id, "applied")
        else:
            self._set_stage(job_id, "applied")
