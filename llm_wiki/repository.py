"""Runtime JSON persistence with schema migration."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from llm_wiki.text import read_text, timestamp, write_text

SCHEMA_VERSION = 2


def migrate_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Migrate legacy state to schema v2 (idempotent)."""
    if not isinstance(raw, dict):
        raw = {}

    if raw.get("schema_version", 0) >= SCHEMA_VERSION and "acquisitions" in raw:
        state = dict(raw)
        state.setdefault("trash", {})
        state.setdefault("acquisitions", [])
        state.setdefault("snapshots", [])
        state.setdefault("jobs", [])
        return state

    state = dict(raw)
    state.setdefault("trash", {})
    acquisitions: list[dict[str, Any]] = list(state.get("acquisitions", []))
    snapshots: list[dict[str, Any]] = list(state.get("snapshots", []))
    existing_snapshot_ids = {item.get("id") for item in snapshots if isinstance(item, dict)}

    legacy_sources = state.get("sources")
    if isinstance(legacy_sources, dict):
        for digest, entry in legacy_sources.items():
            if not isinstance(entry, dict):
                continue
            digest_text = str(entry.get("digest") or digest)
            snap_id = digest_text
            acq_id = f"acq_{digest_text[:12]}"
            if snap_id in existing_snapshot_ids:
                continue

            raw_path = str(entry.get("raw_path", ""))
            status = str(entry.get("status", "archived"))
            acquisition_status = "captured" if raw_path else "queued"
            if status == "failed":
                acquisition_status = "failed"

            acquisitions.append(
                {
                    "id": acq_id,
                    "kind": "file",
                    "origin": raw_path or digest_text,
                    "canonical_origin": raw_path or digest_text,
                    "display_title": str(entry.get("title", Path(raw_path).stem if raw_path else digest_text)),
                    "status": acquisition_status,
                    "latest_snapshot_id": snap_id,
                    "created_at": str(entry.get("ingested_at") or timestamp()),
                    "checked_at": str(entry.get("ingested_at") or timestamp()),
                    "error_code": "",
                }
            )
            snapshots.append(
                {
                    "id": snap_id,
                    "acquisition_id": acq_id,
                    "content_digest": digest_text if digest_text.startswith("sha256:") else f"sha256:{digest_text}",
                    "raw_path": raw_path,
                    "captured_at": str(entry.get("ingested_at") or timestamp()),
                    "content_type": "text/markdown",
                    "etag": "",
                    "last_modified": "",
                    "extractor": "file",
                    "extractor_version": "1",
                }
            )
            existing_snapshot_ids.add(snap_id)

    state["acquisitions"] = acquisitions
    state["snapshots"] = snapshots
    state.setdefault("jobs", [])
    state["schema_version"] = SCHEMA_VERSION
    return state


def migrate_queue(raw: dict[str, Any]) -> dict[str, Any]:
    """Ensure queue tasks include kind and stage fields."""
    queue = dict(raw) if isinstance(raw, dict) else {}
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        queue["tasks"] = []
        return queue

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task.setdefault("kind", "file")
        if "stage" not in task:
            status = str(task.get("status", "queued"))
            task["stage"] = status if status in {"queued", "failed", "processing"} else "queued"
    return queue


class Repository:
    """Short-transaction access to `.llm-wiki` runtime JSON files."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.runtime = self.root / ".llm-wiki"
        self.state_path = self.runtime / "state.json"
        self.queue_path = self.runtime / "queue.json"
        self._lock = threading.RLock()

    def _read_json(self, path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(fallback)
        try:
            value = json.loads(read_text(path))
            return value if isinstance(value, dict) else dict(fallback)
        except json.JSONDecodeError:
            return dict(fallback)

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        write_text(path, json.dumps(value, ensure_ascii=False, indent=2))

    def load_state(self) -> dict[str, Any]:
        with self._lock:
            raw = self._read_json(self.state_path, {"sources": {}, "trash": {}})
            state = migrate_state(raw)
            legacy_sources = raw.get("sources")
            if isinstance(legacy_sources, dict):
                state.setdefault("sources", legacy_sources)
                for entry in legacy_sources.values():
                    if isinstance(entry, dict) and "status" not in entry:
                        entry["status"] = "applied" if entry.get("source_page") else "archived"
            return state

    def save_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            payload = dict(state)
            payload["schema_version"] = SCHEMA_VERSION
            self.runtime.mkdir(parents=True, exist_ok=True)
            self._write_json(self.state_path, payload)

    def load_queue(self) -> dict[str, Any]:
        with self._lock:
            return migrate_queue(self._read_json(self.queue_path, {"tasks": []}))

    def save_queue(self, queue: dict[str, Any]) -> None:
        with self._lock:
            self.runtime.mkdir(parents=True, exist_ok=True)
            self._write_json(self.queue_path, migrate_queue(queue))
