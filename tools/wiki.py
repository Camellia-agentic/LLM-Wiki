#!/usr/bin/env python3
"""Markdown-first local LLM Wiki maintenance tool.

The tool deliberately keeps the raw/source, generated-wiki, and schema layers
separate. It uses only the Python standard library so a new vault works before
an LLM endpoint or vector database is configured.
"""

from __future__ import annotations

import argparse
import difflib
import html
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import time
import webbrowser
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from llm_wiki.control import ControlState, InstanceLock
from llm_wiki.pipeline import analyze_content_in_chunks
from llm_wiki.server import api_error_response, handle_v1_get, handle_v1_post
from llm_wiki.repository import Repository
from llm_wiki.jobs import AcquisitionStore, JobRunner
from llm_wiki.text import PAGE_TYPES
from llm_wiki.errors import ApiError
from llm_wiki.relations import merge_relations_into_content, topic_relations_from_analysis


SOURCE_EXTENSIONS = {".md", ".markdown", ".txt"}
WIKI_DIRECTORIES = ("sources", "concepts", "entities", "queries", "synthesis")
SKIP_WIKI_FILES = {"index.md", "log.md", "overview.md", "reviews.md"}
MAX_QUEUE_ATTEMPTS = 3
REVIEW_KINDS = {"source_claim", "gap", "research_question", "legacy_unanchored"}

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def today() -> str:
    return datetime.now().astimezone().date().isoformat()


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Multiple watch/control processes may update independent runtime files at
    # the same time. A per-write name avoids collisions on Windows.
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def slug(value: str, fallback: str = "page") -> str:
    value = re.sub(r"\s+", "-", value.strip().lower())
    value = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_-]", "", value)
    return value[:72].strip("-_") or fallback


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def frontmatter(title: str, page_type: str, sources: list[str]) -> str:
    lines = ["---", f"title: {yaml_quote(title)}", f"type: {page_type}", "sources:"]
    lines.extend(f"  - {yaml_quote(source)}" for source in sources)
    lines.extend([f"updated: {today()}", "---", ""])
    return "\n".join(lines)


def page_title(content: str, fallback: str) -> str:
    match = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", content, re.MULTILINE)
    if match:
        return match.group(1).strip().strip('"\'')
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def strip_frontmatter(content: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)


def first_heading(content: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def compact(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Never leave an unterminated Obsidian link in generated index excerpts.
    text = re.sub(r"\[\[([^\]]{0,240})\]\]", r"\1", text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def content_hash(path: Path) -> str | None:
    return sha256(path) if path.is_file() else None


def normalise_topic(value: str) -> str:
    return re.sub(r"[\s_\-()（）【】\[\]，,。.:：/]+", "", value.casefold())


def headings(content: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_+.-]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            tokens.extend(part)
            tokens.extend(part[index : index + 2] for index in range(len(part) - 1))
        elif len(part) > 1:
            tokens.append(part)
    return tokens


def source_summary(content: str) -> str:
    body = strip_frontmatter(content)
    paragraphs = []
    for part in re.split(r"\n\s*\n", body):
        cleaned = compact(part, 420)
        if cleaned and not re.fullmatch(r"#{1,6}\s+.+", cleaned):
            paragraphs.append(cleaned)
    return " ".join(paragraphs[:2]) if paragraphs else "原始资料没有可提取的文本内容。"


def safe_json(content: str) -> dict:
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 JSON 对象")
    value = json.loads(content[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型返回的 JSON 根节点不是对象")
    return value


class Wiki:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.inbox = self.root / "raw" / "inbox"
        self.raw = self.root / "raw" / "sources"
        self.wiki = self.root / "wiki"
        self.state_path = self.root / ".llm-wiki" / "state.json"
        self.queue_path = self.root / ".llm-wiki" / "queue.json"
        self.reviews_path = self.root / ".llm-wiki" / "reviews.json"
        self.analysis_dir = self.root / ".llm-wiki" / "analyses"
        self.drafts_dir = self.root / ".llm-wiki" / "drafts"
        self.search_db_path = self.root / ".llm-wiki" / "search.db"

    def ensure_layout(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)
        (self.root / ".llm-wiki").mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        for directory in WIKI_DIRECTORIES:
            (self.wiki / directory).mkdir(parents=True, exist_ok=True)
        for filename, title, page_type in (
            ("index.md", "知识库索引", "index"),
            ("log.md", "知识库操作日志", "log"),
            ("overview.md", "知识库概览", "overview"),
            ("reviews.md", "待人工复核", "review_queue"),
        ):
            path = self.wiki / filename
            if not path.exists():
                write_text(path, frontmatter(title, page_type, []) + f"# {title}\n")
        self.recover_interrupted_drafts()

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {"sources": {}, "trash": {}}
        try:
            value = json.loads(read_text(self.state_path))
            if not isinstance(value, dict) or not isinstance(value.get("sources"), dict):
                return {"sources": {}, "trash": {}}
            value.setdefault("trash", {})
            for entry in value["sources"].values():
                if isinstance(entry, dict) and "status" not in entry:
                    entry["status"] = "applied" if entry.get("source_page") else "archived"
            return value
        except json.JSONDecodeError:
            return {"sources": {}, "trash": {}}

    def save_state(self, state: dict) -> None:
        write_text(self.state_path, json.dumps(state, ensure_ascii=False, indent=2))

    def load_json(self, path: Path, fallback: dict) -> dict:
        if not path.exists():
            return fallback
        try:
            value = json.loads(read_text(path))
            return value if isinstance(value, dict) else fallback
        except json.JSONDecodeError:
            return fallback

    def save_json(self, path: Path, value: dict) -> None:
        write_text(path, json.dumps(value, ensure_ascii=False, indent=2))

    def load_queue(self) -> dict:
        queue = self.load_json(self.queue_path, {"tasks": []})
        if not isinstance(queue.get("tasks"), list):
            queue["tasks"] = []
        for task in queue["tasks"]:
            if task.get("status") == "processing":
                task["status"] = "pending"
                task["error"] = "上次处理被中断，已恢复为待处理。"
        return queue

    def save_queue(self, queue: dict) -> None:
        self.save_json(self.queue_path, queue)

    def analysis_path(self, digest: str) -> Path:
        return self.analysis_dir / f"{digest}.json"

    def save_analysis(self, digest: str, title: str, raw_path: str, analysis: dict, generation: dict | None = None) -> None:
        payload = self.load_json(self.analysis_path(digest), {})
        payload.update({"digest": digest, "title": title, "raw_path": raw_path, "analyzed_at": timestamp(), "analysis": analysis})
        if generation is not None:
            payload["generated_at"] = timestamp()
            payload["generation"] = generation
        self.save_json(self.analysis_path(digest), payload)

    def draft_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", run_id):
            raise ValueError("无效草稿 ID。")
        return self.drafts_dir / run_id

    def draft_manifest_path(self, run_id: str) -> Path:
        return self.draft_path(run_id) / "manifest.json"

    def load_draft(self, run_id: str) -> dict:
        manifest = self.load_json(self.draft_manifest_path(run_id), {})
        if not manifest or manifest.get("id") != run_id:
            raise ValueError("找不到草稿。")
        return manifest

    def save_draft(self, manifest: dict) -> None:
        self.save_json(self.draft_manifest_path(str(manifest["id"])), manifest)

    def list_drafts(self, status: str = "all") -> list[dict]:
        drafts: list[dict] = []
        if not self.drafts_dir.exists():
            return drafts
        for path in sorted(self.drafts_dir.iterdir(), reverse=True):
            if not path.is_dir():
                continue
            manifest = self.load_json(path / "manifest.json", {})
            if manifest and (status == "all" or manifest.get("status") == status):
                drafts.append(manifest)
        return drafts

    def draft_diff(self, manifest: dict) -> list[dict]:
        files_dir = self.draft_path(str(manifest["id"])) / "files"
        diffs: list[dict] = []
        for change in manifest.get("changes", []):
            relative = str(change.get("path", ""))
            target = self.wiki / relative
            candidate = files_dir / relative
            before = read_text(target) if target.is_file() else ""
            after = read_text(candidate) if candidate.is_file() else ""
            diff = "\n".join(
                difflib.unified_diff(
                    before.splitlines(),
                    after.splitlines(),
                    fromfile=f"wiki/{relative}",
                    tofile=f"draft/{relative}",
                    lineterm="",
                )
            )
            diffs.append({"path": relative, "operation": change.get("operation"), "diff": diff})
        candidates = manifest.get("duplicate_candidates", [])
        if candidates:
            text = "\n".join(
                f"疑似重复：{item.get('proposed', '')} / {item.get('existing_title', '')} ({item.get('existing_path', '')})"
                for item in candidates
            )
            diffs.insert(0, {"path": "重复概念候选", "operation": "review", "diff": text})
        return diffs

    def recover_interrupted_drafts(self) -> None:
        if not self.drafts_dir.exists():
            return
        for manifest_path in self.drafts_dir.glob("*/manifest.json"):
            manifest = self.load_json(manifest_path, {})
            if manifest.get("status") != "applying":
                continue
            run_dir = manifest_path.parent
            rollback = self.load_json(run_dir / "rollback.json", {"paths": []})
            for item in rollback.get("paths", []):
                relative = str(item.get("path", ""))
                if not relative:
                    continue
                target = self.wiki / relative
                backup = run_dir / "rollback" / relative
                if item.get("existed") and backup.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, target)
                elif not item.get("existed"):
                    target.unlink(missing_ok=True)
            manifest["status"] = "recovered"
            manifest["recovered_at"] = timestamp()
            self.save_json(manifest_path, manifest)

    def extract_unknown_frontmatter(self, content: str, known: set[str]) -> list[str]:
        header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not header:
            return []
        blocks: list[list[str]] = []
        current: list[str] = []
        current_key = ""
        for line in header.group(1).splitlines():
            match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line)
            if match:
                if current and current_key not in known:
                    blocks.append(current)
                current = [line]
                current_key = match.group(1)
            elif current:
                current.append(line)
        if current and current_key not in known:
            blocks.append(current)
        return ["\n".join(block) for block in blocks]

    def preserve_human_content(self, existing: str, generated: str) -> str:
        unknown = self.extract_unknown_frontmatter(existing, {"title", "type", "sources", "updated", "relations"})
        if unknown:
            generated = generated.replace("\n---\n", "\n" + "\n".join(unknown) + "\n---\n", 1)
        manual = re.search(r"(?ms)^## 人工补充\s*$.*?(?=^## |\Z)", strip_frontmatter(existing))
        if manual and "## 人工补充" not in generated:
            generated = generated.rstrip() + "\n\n" + manual.group(0).rstrip() + "\n"
        return generated

    def topic_path(self, kind: str, name: str) -> Path:
        return self.wiki / kind / f"{slug(name)}.md"

    def render_topic_page(
        self,
        kind: str,
        item: object,
        source_path: str,
        source_title: str,
        existing: str = "",
        *,
        page_relations: list[dict] | None = None,
    ) -> tuple[Path, str, str] | None:
        if isinstance(item, str):
            name, summary = item.strip(), ""
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            summary = str(item.get("summary", "")).strip()
        else:
            return None
        if not name or len(name) > 100:
            return None
        path = self.topic_path(kind, name)
        if not existing:
            heading = "概念" if kind == "concepts" else "实体"
            page_type = PAGE_TYPES.get(kind, kind.rstrip("s"))
            content = frontmatter(name, page_type, [source_path]) + f"# {name}\n\n## {heading}说明\n\n{summary or '待后续资料补充。'}\n"
        else:
            existing_sources = self.frontmatter_sources(existing)
            content = existing
            if source_path not in existing_sources:
                content = self.set_frontmatter_sources(content, [*existing_sources, source_path])
            section = f"\n## {today()} · {source_title}\n\n{summary or '此资料提及该主题。'}\n\n来源：[{source_path}](../../{source_path})\n"
            if source_path not in content:
                content = content.rstrip() + section
        if page_relations:
            content = merge_relations_into_content(content, page_relations)
        if not existing:
            return path, content, name
        return path, content, name

    def duplicate_candidates(self, kind: str, name: str, target: Path) -> list[dict]:
        normalized = normalise_topic(name)
        if len(normalized) < 4:
            return []
        candidates: list[dict] = []
        for page in (self.wiki / kind).glob("*.md"):
            if page == target:
                continue
            content = read_text(page)
            existing_name = page_title(content, page.stem)
            other = normalise_topic(existing_name)
            if len(other) < 4:
                continue
            if normalized in other or other in normalized:
                candidates.append({"kind": kind, "proposed": name, "existing_path": self.relative_wiki_path(page), "existing_title": existing_name})
        return candidates[:6]

    def render_source_pages(self, title: str, raw_path: str, content: str, analysis: dict) -> tuple[dict[str, str], str, list[dict]]:
        digest = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()[:10]
        source_path = self.wiki / "sources" / f"{slug(title, 'source')}-{digest}.md"
        planned: dict[str, str] = {}
        related: list[str] = []
        duplicates: list[dict] = []
        analysis_relations = analysis.get("relations", []) if isinstance(analysis.get("relations"), list) else []

        def wiki_exists(relative: str) -> bool:
            return (self.wiki / f"{relative}.md").is_file()

        for kind, key in (("concepts", "concepts"), ("entities", "entities")):
            values = analysis.get(key, []) if isinstance(analysis.get(key), list) else []
            for item in values:
                name = str(item.get("name", "")).strip() if isinstance(item, dict) else str(item).strip()
                candidate_path = self.topic_path(kind, name) if name else None
                existing = planned.get(self.relative_wiki_path(candidate_path)) if candidate_path else ""
                if candidate_path and not existing and candidate_path.is_file():
                    existing = read_text(candidate_path)
                planned_paths = {path.removesuffix(".md") for path in planned}
                page_relations = topic_relations_from_analysis(
                    analysis_relations,
                    subject=name,
                    source_path=raw_path,
                    planned_paths=planned_paths,
                    wiki_exists=wiki_exists,
                )
                rendered = self.render_topic_page(
                    kind,
                    item,
                    raw_path,
                    title,
                    existing,
                    page_relations=page_relations or None,
                )
                if not rendered:
                    continue
                path, page, topic_name = rendered
                relative = self.relative_wiki_path(path)
                planned[relative] = page
                related.append(f"[[{self.wiki_link(path)}]]")
                duplicates.extend(self.duplicate_candidates(kind, topic_name, path))
        deterministic_summary = source_summary(content)
        summary = str(analysis.get("summary", "")).strip() or deterministic_summary
        lines = [frontmatter(title, "source_summary", [raw_path]), f"# {title}", "", "## 摘要", "", summary, "", "## 原始资料", "", f"[{raw_path}](../../{raw_path})"]
        outline = headings(content)[:18]
        if outline:
            lines.extend(["", "## 原文结构", "", *[f"- {item}" for item in outline]])
        if related:
            lines.extend(["", "## 相关页面", "", *[f"- {item}" for item in sorted(set(related))]])
        links: list[str] = []
        for item in analysis.get("links", []) if isinstance(analysis.get("links"), list) else []:
            link = self.existing_wiki_link(item)
            if link:
                links.append(link)
        if links:
            lines.extend(["", "## 建议关联", ""])
            lines.extend(f"- {item}" for item in sorted(set(links))[:12])
        rendered_source = "\n".join(lines)
        if source_path.is_file():
            rendered_source = self.preserve_human_content(read_text(source_path), rendered_source)
        planned[self.relative_wiki_path(source_path)] = rendered_source
        return planned, self.relative_wiki_path(source_path), duplicates

    def create_draft(self, kind: str, title: str, pages: dict[str, str], *, source: dict | None = None, review_items: object = None, duplicate_candidates: list[dict] | None = None) -> dict:
        run_id = f"{datetime.now().astimezone().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        run_dir = self.draft_path(run_id)
        files_dir = run_dir / "files"
        changes: list[dict] = []
        for relative, content in sorted(pages.items()):
            target = self.wiki / relative
            candidate = files_dir / relative
            write_text(candidate, content)
            base_hash = content_hash(target)
            changes.append({"path": relative, "operation": "create" if base_hash is None else "modify", "base_hash": base_hash, "candidate_hash": content_hash(candidate)})
        created = sum(item["operation"] == "create" for item in changes)
        cleaned_reviews = self.normalise_review_items(
            review_items,
            str((source or {}).get("raw_path", "")),
        )
        manifest = {
            "schema": 2,
            "id": run_id,
            "kind": kind,
            "title": title,
            "status": "draft",
            "created_at": timestamp(),
            "source": source or {},
            "changes": changes,
            "summary": {"created": created, "modified": len(changes) - created, "review_items": len(cleaned_reviews), "duplicate_candidates": len(duplicate_candidates or [])},
            "review_items": cleaned_reviews[:12],
            "duplicate_candidates": duplicate_candidates or [],
        }
        self.save_draft(manifest)
        return manifest

    def apply_draft(self, run_id: str) -> dict:
        manifest = self.load_draft(run_id)
        if manifest.get("status") != "draft":
            raise ValueError("只有待确认草稿可以应用。")
        run_dir = self.draft_path(run_id)
        files_dir = run_dir / "files"
        conflicts = [item["path"] for item in manifest.get("changes", []) if content_hash(self.wiki / item["path"]) != item.get("base_hash")]
        if conflicts:
            raise ValueError("草稿基线已变化，请重新生成：" + "、".join(conflicts))
        rollback = {"paths": []}
        for item in manifest.get("changes", []):
            relative = str(item["path"])
            target = self.wiki / relative
            backup = run_dir / "rollback" / relative
            existed = target.is_file()
            if existed:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            rollback["paths"].append({"path": relative, "existed": existed})
        self.save_json(run_dir / "rollback.json", rollback)
        manifest["status"] = "applying"
        self.save_draft(manifest)
        try:
            for item in manifest.get("changes", []):
                relative = str(item["path"])
                candidate = files_dir / relative
                if not candidate.is_file():
                    raise RuntimeError(f"草稿文件缺失：{relative}")
                write_text(self.wiki / relative, read_text(candidate))
            source = manifest.get("source", {})
            if source.get("digest"):
                state = self.load_state()
                entry = state["sources"].setdefault(str(source["digest"]), {})
                entry.update({"raw_path": source.get("raw_path", ""), "source_page": source.get("source_page", ""), "title": source.get("title", manifest.get("title", "")), "status": "applied", "applied_at": timestamp(), "analysis_path": source.get("analysis_path", "")})
                self.save_state(state)
            if manifest.get("review_items"):
                self.append_reviews(manifest.get("title", "草稿"), str(source.get("raw_path", "")), manifest["review_items"])
            self.append_log("apply", str(manifest.get("title", "草稿")), f"- 已应用草稿：`{run_id}`\n- 页面变更：{len(manifest.get('changes', []))} 项")
            self.rebuild_index()
            self.rebuild_overview()
            self.rebuild_search_index()
        except Exception:
            self.recover_interrupted_drafts()
            raise
        manifest["status"] = "applied"
        manifest["applied_at"] = timestamp()
        self.save_draft(manifest)
        return manifest

    def discard_draft(self, run_id: str) -> dict:
        manifest = self.load_draft(run_id)
        if manifest.get("status") != "draft":
            raise ValueError("只有待确认草稿可以丢弃。")
        shutil.rmtree(self.draft_path(run_id) / "files", ignore_errors=True)
        manifest["status"] = "discarded"
        manifest["discarded_at"] = timestamp()
        self.save_draft(manifest)
        source = manifest.get("source", {})
        if source.get("digest"):
            state = self.load_state()
            entry = state["sources"].setdefault(str(source["digest"]), {})
            entry["status"] = "archived"
            entry["draft_id"] = run_id
            self.save_state(state)
        return manifest

    def trash_source(self, target: Path | str) -> dict:
        found = self.find_source_entry(target)
        if not found:
            raise ValueError("找不到对应的已归档资料。")
        digest, entry = found
        if entry.get("status") == "trashed":
            return entry
        state = self.load_state()
        entry = state["sources"][digest]
        entry["status_before_trash"] = entry.get("status", "applied")
        entry["status"] = "trashed"
        entry["trashed_at"] = timestamp()
        state["trash"][digest] = {"raw_path": entry.get("raw_path", ""), "title": entry.get("title", Path(str(entry.get("raw_path", "source"))).stem), "trashed_at": entry["trashed_at"]}
        self.save_state(state)
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()
        return entry

    def restore_source(self, digest: str) -> dict:
        state = self.load_state()
        entry = state["sources"].get(digest)
        if not entry or entry.get("status") != "trashed":
            raise ValueError("找不到可恢复的资料。")
        entry["status"] = entry.pop("status_before_trash", "applied")
        entry["restored_at"] = timestamp()
        state["trash"].pop(digest, None)
        self.save_state(state)
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()
        return entry

    def list_trash(self) -> list[dict]:
        state = self.load_state()
        return [{"digest": digest, **item} for digest, item in state.get("trash", {}).items()]

    def add_topic_alias(self, kind: str, target: str, alias: str) -> Path:
        if kind not in {"concepts", "entities"}:
            raise ValueError("只能为概念或实体添加别名。")
        safe_target = Path(target).name.removesuffix(".md")
        path = self.wiki / kind / f"{safe_target}.md"
        if not path.is_file():
            raise ValueError("找不到目标页面。")
        alias = alias.strip()
        if not alias or len(alias) > 100:
            raise ValueError("别名不能为空且不能超过 100 个字符。")
        content = read_text(path)
        header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not header:
            raise ValueError("目标页面缺少 frontmatter。")
        aliases = re.search(r"^aliases:\n((?:  - .+\n?)*)", header.group(1), re.MULTILINE)
        existing = []
        if aliases:
            existing = [line.removeprefix("  - ").strip().strip('"') for line in aliases.group(1).splitlines()]
        if alias not in existing:
            lines = header.group(1).splitlines()
            if aliases:
                start, end = aliases.span()
                replacement = "aliases:\n" + "\n".join(f"  - {yaml_quote(value)}" for value in [*existing, alias])
                new_header = header.group(1)[:start] + replacement + header.group(1)[end:]
            else:
                new_header = header.group(1).rstrip() + "\naliases:\n  - " + yaml_quote(alias) + "\n"
            content = "---\n" + new_header.rstrip() + "\n---\n" + content[header.end() :]
            write_text(path, content)
            self.rebuild_index()
            self.rebuild_search_index()
        return path

    def merge_topic_pages(self, kind: str, source: str, target: str) -> Path:
        if kind not in {"concepts", "entities"}:
            raise ValueError("只能合并概念或实体页面。")
        source_path = self.wiki / kind / f"{Path(source).name.removesuffix('.md')}.md"
        target_path = self.wiki / kind / f"{Path(target).name.removesuffix('.md')}.md"
        if source_path == target_path or not source_path.is_file() or not target_path.is_file():
            raise ValueError("合并页面不存在或目标无效。")
        source_content = read_text(source_path)
        target_content = read_text(target_path)
        source_title = page_title(source_content, source_path.stem)
        self.add_topic_alias(kind, target_path.stem, source_title)
        target_content = read_text(target_path)
        target_content = self.set_frontmatter_sources(target_content, [*self.frontmatter_sources(target_content), *self.frontmatter_sources(source_content)])
        target_content = target_content.rstrip() + f"\n\n## 合并记录\n\n合并自 [[wiki/{kind}/{source_path.stem}]]。\n"
        write_text(target_path, target_content)
        source_link = f"[[wiki/{kind}/{source_path.stem}]]"
        target_link = f"[[wiki/{kind}/{target_path.stem}]]"
        for page in self.all_wiki_pages():
            content = read_text(page)
            if source_link in content:
                write_text(page, content.replace(source_link, target_link))
        source_path.unlink()
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()
        self.append_log("merge", source_title, f"- 合并到：[[wiki/{kind}/{target_path.stem}]]")
        return target_path

    def status_summary(self) -> dict:
        queue = self.load_queue()["tasks"]
        reviews = self.load_reviews()["items"]
        drafts = self.list_drafts()
        broken, orphans, missing_sources = self.lint()
        inbox = []
        for path in collect_sources(self.inbox, recursive=True):
            inbox.append({"name": path.relative_to(self.inbox).as_posix(), "size": path.stat().st_size, "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M")})
        sources = []
        for digest, entry in self.load_state()["sources"].items():
            raw_path = str(entry.get("raw_path", ""))
            if raw_path:
                sources.append({"digest": digest, "title": entry.get("title", Path(raw_path).stem), "raw_path": raw_path, "status": entry.get("status", "archived")})
        return {
            "inbox": inbox,
            "sources": sorted(sources, key=lambda item: (item["status"] == "trashed", item["title"])),
            "queue": {status: sum(item.get("status") == status for item in queue) for status in ("pending", "processing", "failed", "completed")},
            "drafts": {status: sum(item.get("status") == status for item in drafts) for status in ("draft", "applied", "discarded", "recovered")},
            "reviews": {
                "open": sum(item.get("status") == "open" and self.review_queue(item) == "facts" for item in reviews),
                "resolved": sum(item.get("status") == "resolved" and self.review_queue(item) == "facts" for item in reviews),
                "research_open": sum(item.get("status") == "open" and self.review_queue(item) == "research" for item in reviews),
                "research_resolved": sum(item.get("status") == "resolved" and self.review_queue(item) == "research" for item in reviews),
            },
            "trash": len(self.list_trash()),
            "health": {"broken_links": len(broken), "orphan_pages": len(orphans), "missing_sources": len(missing_sources)},
        }

    def is_trashed_raw_path(self, raw_path: str) -> bool:
        for entry in self.load_state()["sources"].values():
            if entry.get("raw_path") == raw_path:
                return entry.get("status") == "trashed"
        return False

    def is_visible_page(self, path: Path, content: str | None = None) -> bool:
        content = content if content is not None else read_text(path)
        raw_sources = [source for source in self.frontmatter_sources(content) if source.startswith("raw/")]
        return not raw_sources or not all(self.is_trashed_raw_path(source) for source in raw_sources)

    def directory_pages(self, directory: str, visible_only: bool = True) -> list[Path]:
        pages = sorted((self.wiki / directory).glob("*.md"))
        return [path for path in pages if not visible_only or self.is_visible_page(path)]

    def wiki_pages(self) -> list[Path]:
        pages: list[Path] = []
        for directory in WIKI_DIRECTORIES:
            pages.extend(self.directory_pages(directory))
        return pages

    def all_wiki_pages(self) -> list[Path]:
        return sorted(path for path in self.wiki.rglob("*.md") if path.name not in {".gitkeep"})

    def relative_wiki_path(self, path: Path) -> str:
        return path.relative_to(self.wiki).as_posix()

    def wiki_link(self, path: Path) -> str:
        return f"wiki/{self.relative_wiki_path(path).removesuffix('.md')}"

    def raw_destination(self, source: Path, digest: str) -> Path:
        try:
            relative = source.resolve().relative_to(self.raw.resolve())
            return self.raw / relative
        except ValueError:
            base = slug(source.stem, "source")
            return self.raw / f"{base}-{digest[:10]}{source.suffix.lower()}"

    def copy_source(self, source: Path, digest: str) -> tuple[Path, str]:
        target = self.raw_destination(source, digest)
        if source.resolve() != target.resolve() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return target, target.relative_to(self.root).as_posix()

    def llm_request(self, messages: list[dict], args: argparse.Namespace, *, json_mode: bool = False, temperature: float = 0.1) -> str:
        if not args.llm_url or not args.model:
            raise ValueError("未配置 LLM endpoint 或 model。")
        payload = {"model": args.model, "temperature": temperature, "messages": messages}
        if getattr(args, "max_tokens", None):
            payload["max_tokens"] = args.max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if args.api_key:
            headers["Authorization"] = f"Bearer {args.api_key}"

        def complete(body: dict) -> dict:
            retryable = {429, 502, 503}
            last_error: HTTPError | None = None
            for attempt in range(4):
                try:
                    request = Request(args.llm_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                    with urlopen(request, timeout=args.timeout) as response:
                        return json.loads(response.read().decode("utf-8"))
                except HTTPError as error:
                    if error.code in retryable and attempt < 3:
                        delay = min(2 ** attempt, 16)
                        print(f"  模型服务繁忙（HTTP {error.code}），{delay}s 后重试…", file=sys.stderr)
                        time.sleep(delay)
                        last_error = error
                        continue
                    raise
            if last_error:
                raise last_error
            raise RuntimeError("模型请求失败。")

        try:
            response_data = complete(payload)
        except HTTPError as error:
            if not json_mode or error.code not in {400, 404, 422}:
                raise
            payload.pop("response_format", None)
            response_data = complete(payload)
        return response_data["choices"][0]["message"]["content"]

    def llm_json(self, system: str, user: str, args: argparse.Namespace, label: str) -> dict:
        try:
            return safe_json(self.llm_request([{"role": "system", "content": system}, {"role": "user", "content": user}], args, json_mode=True))
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
            print(f"  模型{label}失败：{error}", file=sys.stderr)
            return {}

    def llm_analysis(self, title: str, raw_path: str, content: str, args: argparse.Namespace) -> dict:
        if not args.llm_url or not args.model:
            return {}
        return analyze_content_in_chunks(self, title, raw_path, content, args, self.llm_json)

    def llm_generation(self, title: str, raw_path: str, analysis: dict, args: argparse.Namespace) -> dict:
        system = (
            "You are stage 2 of a Chinese knowledge-wiki ingest pipeline. Return only a JSON object. "
            "Use the supplied analysis only; do not add unsupported facts. Produce concise, maintainable page content. "
            "Schema: {summary:string, concepts:[{name:string,summary:string}], entities:[{name:string,summary:string}], "
            "links:[string], review_items:[{kind:string,text:string,evidence_quote:string,evidence_anchor:string,confidence:string}]}. "
            "Copy review_items from stage 1 unchanged. Do not add, remove, reclassify, or paraphrase review items."
        )
        user = f"Source: {raw_path}\nTitle: {title}\n\nStage 1 analysis:\n{json.dumps(analysis, ensure_ascii=False)}"
        return self.llm_json(system, user, args, "第二阶段生成")

    def generate_from_source(self, title: str, raw_path: str, content: str, digest: str, args: argparse.Namespace) -> dict:
        if not args.llm_url or not args.model:
            return {}
        analysis = self.llm_analysis(title, raw_path, content, args)
        if not analysis:
            raise RuntimeError("第一阶段分析没有返回有效结果。")
        self.save_analysis(digest, title, raw_path, analysis)
        generation = self.llm_generation(title, raw_path, analysis, args)
        if not generation:
            raise RuntimeError("第二阶段生成没有返回有效结果。")
        # Review items are evidence records from stage 1. Stage 2 may render pages,
        # but cannot add unsupported audit work or weaken the evidence gate.
        generation["review_items"] = self.normalise_review_items(analysis.get("review_items"), raw_path, content)
        self.save_analysis(digest, title, raw_path, analysis, generation)
        return generation

    def frontmatter_sources(self, content: str) -> list[str]:
        match = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not match:
            return []
        sources = re.search(r"^sources:\n((?:  - .+\n?)*)", match.group(1), re.MULTILINE)
        if not sources:
            return []
        values = []
        for line in sources.group(1).splitlines():
            value = line.removeprefix("  - ").strip()
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value.strip('"\'')
            if value:
                values.append(str(value))
        return values

    def set_frontmatter_sources(self, content: str, sources: list[str]) -> str:
        header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not header:
            return content
        updated_lines: list[str] = []
        lines = header.group(1).splitlines()
        index = 0
        replaced = False
        while index < len(lines):
            if lines[index] == "sources:":
                updated_lines.append("sources:")
                updated_lines.extend(f"  - {yaml_quote(value)}" for value in sorted(set(sources)))
                replaced = True
                index += 1
                while index < len(lines) and lines[index].startswith("  - "):
                    index += 1
                continue
            updated_lines.append(lines[index])
            index += 1
        if not replaced:
            updated_lines.extend(["sources:", *[f"  - {yaml_quote(value)}" for value in sorted(set(sources))]])
        return "---\n" + "\n".join(updated_lines).rstrip() + "\n---\n" + content[header.end() :]

    def update_topic_page(self, kind: str, item: object, source_path: str, source_title: str) -> Path | None:
        name = str(item.get("name", "")).strip() if isinstance(item, dict) else str(item).strip()
        path = self.topic_path(kind, name) if name else None
        existing = read_text(path) if path and path.is_file() else ""
        rendered = self.render_topic_page(kind, item, source_path, source_title, existing)
        if not rendered:
            return None
        path, content, _ = rendered
        write_text(path, content)
        return path

    def write_source_page(self, title: str, raw_path: str, content: str, analysis: dict) -> Path:
        pages, source_relative, _ = self.render_source_pages(title, raw_path, content, analysis)
        for relative, page in pages.items():
            write_text(self.wiki / relative, page)
        return self.wiki / source_relative

    def append_log(self, kind: str, title: str, details: str = "") -> None:
        log = self.wiki / "log.md"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{timestamp()}] {kind} | {title}\n\n")
            if details:
                handle.write(details.rstrip() + "\n")

    def review_source_content(self, raw_path: str) -> str:
        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("raw/"):
            path = self.root / normalized
        elif normalized.removeprefix("wiki/").split("/", 1)[0] in WIKI_DIRECTORIES:
            path = self.wiki / normalized.removeprefix("wiki/")
        else:
            return ""
        return read_text(path) if path.is_file() else ""

    def evidence_anchor(self, content: str, quote: str) -> str:
        start = content.find(quote)
        if start < 0:
            return ""
        first = content.count("\n", 0, start) + 1
        last = content.count("\n", 0, start + len(quote)) + 1
        return f"第 {first} 行" if first == last else f"第 {first}-{last} 行"

    def normalise_review_items(self, items: object, raw_path: str, source_content: str | None = None) -> list[dict]:
        if not isinstance(items, list):
            return []
        content = source_content if source_content is not None else self.review_source_content(raw_path)
        normalised: list[dict] = []
        for item in items[:12]:
            if isinstance(item, str):
                text = item.strip()
                value = {"kind": "research_question", "text": text, "evidence_quote": "", "evidence_anchor": "", "confidence": ""}
            elif isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                kind = str(item.get("kind", "")).strip().lower()
                quote = str(item.get("evidence_quote", "")).strip()
                confidence = str(item.get("confidence", "")).strip()[:80]
                if kind not in {"source_claim", "gap", "research_question"}:
                    kind = "research_question"
                if kind == "source_claim" and quote and quote in content:
                    quote = quote[:2000]
                    value = {
                        "kind": "source_claim",
                        "text": text,
                        "evidence_quote": quote,
                        "evidence_anchor": self.evidence_anchor(content, quote),
                        "confidence": confidence,
                    }
                else:
                    # A claim without a source quote cannot be presented as a fact to verify.
                    value = {"kind": kind if kind != "source_claim" else "research_question", "text": text, "evidence_quote": "", "evidence_anchor": "", "confidence": confidence}
            else:
                continue
            if value["text"]:
                normalised.append(value)
        return normalised

    def review_queue(self, item: dict) -> str:
        return "facts" if item.get("kind") == "source_claim" and item.get("evidence_quote") else "research"

    def load_reviews(self) -> dict:
        reviews = self.load_json(self.reviews_path, {"schema": 2, "items": []})
        if not isinstance(reviews.get("items"), list):
            reviews["items"] = []
        changed = reviews.get("schema") != 2
        reviews["schema"] = 2
        for item in reviews["items"]:
            if not isinstance(item, dict):
                continue
            if item.get("kind") not in REVIEW_KINDS:
                item.update({
                    "kind": "legacy_unanchored",
                    "evidence_quote": "",
                    "evidence_anchor": "",
                    "migration_note": "旧版审核项未保存可验证的原文引句，已转入待补充。",
                    "migrated_at": timestamp(),
                })
                changed = True
            item.setdefault("resolution_note", "")
            item.setdefault("resolved_at", "")
        if reviews["items"] or self.reviews_path.exists():
            if changed:
                self.save_reviews(reviews)
            return reviews
        legacy = self.wiki / "reviews.md"
        if not legacy.exists():
            return reviews
        for block in re.split(r"\n## ", read_text(legacy))[1:]:
            header, _, body = block.partition("\n")
            source = re.search(r"来源：\[([^\]]+)\]", body)
            title = header.split(" · ", 1)[-1].strip()
            raw_path = source.group(1) if source else ""
            for marker, text in re.findall(r"- \[([ xX])\]\s+(.+)", body):
                review_id = hashlib.sha256(f"{raw_path}\n{text}".encode("utf-8")).hexdigest()[:12]
                reviews["items"].append({"id": review_id, "title": title, "raw_path": raw_path, "text": text, "kind": "legacy_unanchored", "evidence_quote": "", "evidence_anchor": "", "status": "resolved" if marker.lower() == "x" else "open", "created_at": timestamp(), "resolved_at": "", "resolution_note": "", "migration_note": "旧版审核项未保存可验证的原文引句，已转入待补充。", "migrated_at": timestamp()})
        if reviews["items"]:
            self.save_json(self.reviews_path, reviews)
        return reviews

    def save_reviews(self, reviews: dict) -> None:
        reviews["schema"] = 2
        self.save_json(self.reviews_path, reviews)
        lines = [frontmatter("审核与补充队列", "review_queue", []), "# 审核与补充队列", "", "> 只有带有可回溯原文引句的 source_claim 才会进入“待核实事实”。没有证据的缺口、研究问题和旧记录统一进入“待补充”。"]
        for queue, heading in (("facts", "待核实事实"), ("research", "待补充")):
            lines.extend(["", f"## {heading}"])
            for status, label, mark in (("open", "待处理", " "), ("resolved", "已处理", "x")):
                items = [item for item in reviews["items"] if item.get("status") == status and self.review_queue(item) == queue]
                lines.extend(["", f"### {label}", ""])
                if not items:
                    lines.append("_暂无事项。_")
                    continue
                for item in items:
                    source = str(item.get("raw_path", ""))
                    lines.append(f"- [{mark}] `{item['id']}` {item['text']}  ")
                    if queue == "facts":
                        lines.append(f"  原文定位：{item.get('evidence_anchor', '已提供引句')}  ")
                        lines.extend(f"  > {line}" for line in str(item.get("evidence_quote", "")).splitlines())
                    else:
                        label = "旧记录" if item.get("kind") == "legacy_unanchored" else "类型"
                        detail = item.get("migration_note") if item.get("kind") == "legacy_unanchored" else item.get("kind", "research_question")
                        lines.append(f"  {label}：{detail}  ")
                    lines.append(f"  相关资料：[{source}](../{source})" if source.startswith("raw/") else f"  相关资料：{source}")
                    if item.get("resolution_note"):
                        lines.append(f"  处理记录：{item['resolution_note']}")
        write_text(self.wiki / "reviews.md", "\n".join(lines))

    def append_reviews(self, source_title: str, raw_path: str, items: object) -> None:
        clean = self.normalise_review_items(items, raw_path)
        if not clean:
            return
        reviews = self.load_reviews()
        existing = {(item.get("raw_path"), item.get("kind"), item.get("text"), item.get("evidence_quote")) for item in reviews["items"]}
        for value in clean:
            key = (raw_path, value["kind"], value["text"], value["evidence_quote"])
            if key in existing:
                continue
            review_id = hashlib.sha256("\n".join(key).encode("utf-8")).hexdigest()[:12]
            reviews["items"].append({"id": review_id, "title": source_title, "raw_path": raw_path, **value, "status": "open", "created_at": timestamp(), "resolved_at": "", "resolution_note": ""})
            existing.add(key)
        self.save_reviews(reviews)

    def set_review_status(self, review_id: str, status: str, resolution_note: str | None = None) -> bool:
        reviews = self.load_reviews()
        for item in reviews["items"]:
            if item.get("id") == review_id:
                item["status"] = status
                item["resolved_at"] = timestamp() if status == "resolved" else ""
                if resolution_note is not None:
                    item["resolution_note"] = resolution_note.strip()[:4000]
                self.save_reviews(reviews)
                return True
        return False

    def review_detail(self, review_id: str) -> dict:
        item = next((value for value in self.load_reviews()["items"] if value.get("id") == review_id), None)
        if not item:
            raise ValueError("找不到审核项。")
        raw_path = str(item.get("raw_path", "")).replace("\\", "/")
        evidence_path: Path | None = None
        if raw_path.startswith("raw/"):
            candidate = self.root / raw_path
            evidence_path = candidate if candidate.is_file() else None
        elif raw_path.removeprefix("wiki/").split("/", 1)[0] in WIKI_DIRECTORIES:
            candidate = self.wiki / raw_path.removeprefix("wiki/")
            evidence_path = candidate if candidate.is_file() else None
        source_page: Path | None = None
        for entry in self.load_state()["sources"].values():
            if entry.get("raw_path") == raw_path and entry.get("source_page"):
                candidate = self.wiki / str(entry["source_page"])
                source_page = candidate if candidate.is_file() else None
                break
        if source_page is None and evidence_path and evidence_path.is_relative_to(self.wiki):
            source_page = evidence_path

        def content(path: Path | None) -> str:
            if not path:
                return "资料文件当前不可用。"
            value = read_text(path)
            return value if len(value) <= 100_000 else value[:100_000] + "\n\n[正文过长，已截断显示]"

        return {
            "review": item,
            "evidence": {"path": raw_path, "absolute_path": str(evidence_path) if evidence_path else "", "content": content(evidence_path), "quote": item.get("evidence_quote", ""), "anchor": item.get("evidence_anchor", "")},
            "wiki_page": {"path": self.relative_wiki_path(source_page) if source_page else "", "absolute_path": str(source_page) if source_page else "", "content": content(source_page)},
        }

    def rebuild_index(self) -> None:
        sections = [("资料摘要", "sources"), ("概念", "concepts"), ("实体", "entities"), ("分析与问答", "queries"), ("综合分析", "synthesis")]
        lines = [frontmatter("知识库索引", "index", []), "# 知识库索引", "", "> 本页由 `tools/wiki.py` 维护。先从这里定位主题，再阅读相关页面。"]
        for label, folder in sections:
            pages = self.directory_pages(folder)
            lines.extend(["", f"## {label}", ""])
            if not pages:
                lines.append("_暂无页面。_")
                continue
            for path in pages:
                content = read_text(path)
                title = page_title(content, path.stem)
                description = source_summary(content)
                lines.append(f"- [[{self.wiki_link(path)}|{title}]] - {compact(description, 160)}")
        write_text(self.wiki / "index.md", "\n".join(lines))

    def rebuild_overview(self) -> None:
        sources = sorted(self.directory_pages("sources"), key=lambda item: item.stat().st_mtime, reverse=True)
        concepts = self.directory_pages("concepts")
        entities = self.directory_pages("entities")
        lines = [frontmatter("知识库概览", "overview", []), "# 知识库概览", "", f"已沉淀 {len(sources)} 份资料摘要、{len(concepts)} 个概念页、{len(entities)} 个实体页。"]
        if sources:
            lines.extend(["", "## 最近资料", ""])
            for path in sources[:8]:
                lines.append(f"- [[{self.wiki_link(path)}|{page_title(read_text(path), path.stem)}]]")
        lines.extend(["", "## 维护提示", "", "- 原始资料位于 `raw/sources/`，Wiki 页面必须保留来源链接。", "- 定期运行 `python tools/wiki.py lint` 并处理 `wiki/reviews.md`。"])
        write_text(self.wiki / "overview.md", "\n".join(lines))

    def rebuild_derived(self) -> None:
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()

    def ingest(self, source: Path, args: argparse.Namespace) -> bool:
        if source.suffix.lower() not in SOURCE_EXTENSIONS:
            return False
        digest = sha256(source)
        state = self.load_state()
        existing = state["sources"].get(digest, {})
        if existing.get("status") in {"applied", "draft", "trashed"}:
            print(f"跳过（内容未变）：{source}")
            return False
        target, raw_path = self.copy_source(source, digest)
        content = read_text(target)
        title = first_heading(content, source.stem)
        entry = state["sources"].setdefault(digest, {})
        entry.update({"raw_path": raw_path, "title": title, "status": "archived", "archived_at": timestamp()})
        self.save_state(state)
        generation = self.generate_from_source(title, raw_path, content, digest, args)
        if generation and not getattr(args, "apply", False) and not getattr(args, "auto_accept", False):
            pages, source_page, duplicates = self.render_source_pages(title, raw_path, content, generation)
            manifest = self.create_draft(
                "ingest",
                title,
                pages,
                source={"digest": digest, "raw_path": raw_path, "source_page": source_page, "title": title, "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix()},
                review_items=generation.get("review_items", []),
                duplicate_candidates=duplicates,
            )
            state = self.load_state()
            state["sources"][digest].update({"status": "draft", "draft_id": manifest["id"], "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix()})
            self.save_state(state)
            print(f"已归档：{source} -> {raw_path}；草稿待确认：{manifest['id']}")
            return True
        page = self.write_source_page(title, raw_path, content, generation)
        self.append_reviews(title, raw_path, generation.get("review_items", []))
        self.append_log("ingest", title, f"- 原始资料：[{raw_path}](../{raw_path})\n- 摘要：[[{self.wiki_link(page)}]]")
        state = self.load_state()
        state["sources"][digest].update({"raw_path": raw_path, "source_page": self.relative_wiki_path(page), "ingested_at": timestamp(), "status": "applied", "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix() if generation else ""})
        self.save_state(state)
        print(f"已导入：{source} -> {raw_path}")
        return True

    def refine(self, source: Path, args: argparse.Namespace) -> bool:
        source = source.resolve()
        try:
            raw_path = source.relative_to(self.root).as_posix()
        except ValueError as error:
            raise ValueError("refine 只能处理当前知识库内的归档资料。") from error
        if not raw_path.startswith("raw/sources/") or source.suffix.lower() not in SOURCE_EXTENSIONS:
            raise ValueError("refine 只能处理 raw/sources 中的 Markdown/TXT 文件。")
        content = read_text(source)
        title = first_heading(content, source.stem)
        digest = sha256(source)
        generation = self.generate_from_source(title, raw_path, content, digest, args)
        if not generation:
            raise ValueError("没有获得模型分析结果；请检查 --llm-url、--model 和 API Key。")
        if not getattr(args, "apply", False) and not getattr(args, "auto_accept", False):
            pages, source_page, duplicates = self.render_source_pages(title, raw_path, content, generation)
            manifest = self.create_draft(
                "refine",
                title,
                pages,
                source={"digest": digest, "raw_path": raw_path, "source_page": source_page, "title": title, "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix()},
                review_items=generation.get("review_items", []),
                duplicate_candidates=duplicates,
            )
            state = self.load_state()
            entry = state["sources"].setdefault(digest, {})
            entry.update({"raw_path": raw_path, "title": title, "status": "draft", "draft_id": manifest["id"], "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix()})
            self.save_state(state)
            print(f"已生成重新提炼草稿：{manifest['id']}")
            return True
        page = self.write_source_page(title, raw_path, content, generation)
        self.append_reviews(title, raw_path, generation.get("review_items", []))
        self.append_log("refine", title, f"- 原始资料：[{raw_path}](../{raw_path})\n- 更新摘要：[[{self.wiki_link(page)}]]")
        state = self.load_state()
        entry = state["sources"].setdefault(digest, {})
        entry.update({"raw_path": raw_path, "source_page": self.relative_wiki_path(page), "refined_at": timestamp(), "status": "applied", "analysis_path": self.analysis_path(digest).relative_to(self.root).as_posix()})
        self.save_state(state)
        print(f"已用模型重新提炼：{source}")
        return True

    def enqueue_source(self, source: Path) -> str | None:
        source = source.resolve()
        digest = sha256(source)
        if digest in self.load_state()["sources"]:
            return None
        queue = self.load_queue()
        task_id = hashlib.sha256(f"{source}\n{digest}".encode("utf-8")).hexdigest()[:12]
        if any(task.get("id") == task_id for task in queue["tasks"]):
            return task_id
        queue["tasks"].append({"id": task_id, "source": str(source), "digest": digest, "status": "pending", "attempts": 0, "error": "", "created_at": timestamp(), "updated_at": timestamp()})
        self.save_queue(queue)
        return task_id

    def process_queue(self, args: argparse.Namespace, max_attempts: int = MAX_QUEUE_ATTEMPTS) -> dict:
        queue = self.load_queue()
        result = {"completed": 0, "failed": 0, "skipped": 0, "applied": 0, "drafted": 0}
        for task in queue["tasks"]:
            if task.get("status") not in {"pending", "failed"} or int(task.get("attempts", 0)) >= max_attempts:
                continue
            source = Path(task.get("source", ""))
            if not source.is_file():
                task.update({"status": "failed", "attempts": int(task.get("attempts", 0)) + 1, "error": "收件箱文件已不存在。", "updated_at": timestamp()})
                result["failed"] += 1
                self.save_queue(queue)
                continue
            if sha256(source) != task.get("digest"):
                task.update({"status": "failed", "attempts": int(task.get("attempts", 0)) + 1, "error": "文件在入队后发生变化，等待新的稳定版本。", "updated_at": timestamp()})
                result["failed"] += 1
                self.save_queue(queue)
                continue
            task.update({"status": "processing", "attempts": int(task.get("attempts", 0)) + 1, "error": "", "updated_at": timestamp()})
            self.save_queue(queue)
            try:
                imported = self.ingest(source, args)
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
                task.update({"status": "failed", "error": str(error), "updated_at": timestamp()})
                result["failed"] += 1
            else:
                task.update({"status": "completed", "error": "", "updated_at": timestamp()})
                result["completed" if imported else "skipped"] += 1
                source_state = self.load_state()["sources"].get(str(task.get("digest", "")), {})
                if imported and source_state.get("status") == "applied":
                    result["applied"] += 1
                elif imported and source_state.get("status") == "draft":
                    result["drafted"] += 1
            self.save_queue(queue)
        if result["applied"]:
            self.rebuild_index()
            self.rebuild_overview()
            self.rebuild_search_index()
        return result

    def retry_queue_task(self, task_id: str) -> bool:
        queue = self.load_queue()
        for task in queue["tasks"]:
            if task.get("id") == task_id:
                task.update({"status": "pending", "attempts": 0, "error": "", "updated_at": timestamp()})
                self.save_queue(queue)
                return True
        return False

    def existing_wiki_link(self, value: object) -> str | None:
        match = re.fullmatch(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", str(value).strip())
        if not match:
            return None
        target = match.group(1).strip().removesuffix(".md").removeprefix("wiki/")
        candidate = self.wiki / f"{target}.md"
        return f"[[wiki/{target}]]" if candidate.is_file() else None

    def synthesize(self, topic: str, args: argparse.Namespace, max_pages: int = 8) -> Path:
        if not args.llm_url or not args.model:
            raise ValueError("synthesize 需要 --llm-url 和 --model。")
        hits = self.search(topic, max_pages) if topic else []
        pages = [path for _, path, _ in hits] if hits else sorted((self.wiki / "sources").glob("*.md"))[:max_pages]
        if len(pages) < 2:
            raise ValueError("至少需要两份资料摘要才能生成跨资料综合。")
        context = "\n\n".join(f"[{self.wiki_link(path)}]\n{read_text(path)[:4000]}" for path in pages)
        system = (
            "You create a Chinese cross-source wiki synthesis. Return only a JSON object. "
            "Use only the supplied pages, distinguish facts from inference, and preserve unresolved questions. "
            "Schema: {title:string, summary:string, findings:[string], comparisons:[string], "
            "open_questions:[string], related_pages:[string]}."
        )
        user = f"Topic: {topic or '当前知识库跨资料综合'}\n\nSource pages:\n{context}"
        result = self.llm_json(system, user, args, "跨资料综合")
        if not result:
            raise RuntimeError("跨资料综合没有返回有效结果。")
        title = str(result.get("title", "")).strip() or topic or "跨资料综合"
        source_refs = [self.relative_wiki_path(path) for path in pages]
        lines = [frontmatter(title, "synthesis", source_refs), f"# {title}", "", "## 摘要", "", str(result.get("summary", "根据当前资料无法形成可靠综合。"))]
        for key, heading in (("findings", "关键发现"), ("comparisons", "比较与关联"), ("open_questions", "待研究问题")):
            values = [str(value).strip() for value in result.get(key, []) if str(value).strip()] if isinstance(result.get(key), list) else []
            if values:
                lines.extend(["", f"## {heading}", "", *[f"- {value}" for value in values]])
        related = [link for link in (self.existing_wiki_link(value) for value in result.get("related_pages", []) if isinstance(result.get("related_pages"), list)) if link]
        if related:
            lines.extend(["", "## 相关页面", "", *[f"- {link}" for link in sorted(set(related))]])
        path = self.wiki / "synthesis" / f"{slug(title, 'synthesis')}.md"
        rendered = "\n".join(lines)
        if path.is_file():
            rendered = self.preserve_human_content(read_text(path), rendered)
        if not getattr(args, "apply", False) and not getattr(args, "auto_accept", False):
            manifest = self.create_draft(
                "synthesize",
                title,
                {self.relative_wiki_path(path): rendered},
                source={"raw_path": self.relative_wiki_path(path)},
                review_items=[{"kind": "research_question", "text": str(item)} for item in result.get("open_questions", []) if str(item).strip()],
            )
            print(f"已生成跨资料综合草稿：{manifest['id']}")
            return self.draft_path(manifest["id"])
        write_text(path, rendered)
        self.append_reviews(title, self.relative_wiki_path(path), [{"kind": "research_question", "text": str(item)} for item in result.get("open_questions", []) if str(item).strip()])
        self.append_log("synthesize", title, f"- 已保存：[[{self.wiki_link(path)}]]")
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()
        return path

    def find_source_entry(self, target: Path | str) -> tuple[str, dict] | None:
        raw_target = str(target).replace("\\", "/").removesuffix(".md")
        raw_target = raw_target.removeprefix("wiki/")
        for digest, entry in self.load_state()["sources"].items():
            raw_path = str(entry.get("raw_path", ""))
            source_page = str(entry.get("source_page", ""))
            candidates = {raw_path, raw_path.removesuffix(".md"), source_page, source_page.removesuffix(".md")}
            if raw_target in candidates or Path(raw_target).name in {Path(value).name for value in candidates}:
                return digest, entry
        return None

    def remove_source(self, target: Path | str) -> str:
        found = self.find_source_entry(target)
        if not found:
            raise ValueError("找不到对应的已归档资料。")
        digest, entry = found
        raw_path = str(entry["raw_path"])
        source_page = str(entry["source_page"])
        source_stem = source_page.removesuffix(".md")
        source_file = self.wiki / source_page
        for page in self.all_wiki_pages():
            if page == source_file:
                continue
            content = read_text(page)
            original_sources = self.frontmatter_sources(content)
            content = re.sub(rf"(?m)^.*\[\[wiki/{re.escape(source_stem)}(?:\|[^\]]+)?\]\].*\n?", "", content)
            content = re.sub(rf"\n## [^\n]+\n(?:(?!\n## ).)*?来源：\[{re.escape(raw_path)}\]\([^\)]*\)\n?", "\n", content, flags=re.DOTALL)
            sources = [value for value in original_sources if value not in {raw_path, source_page, source_stem, f"wiki/{source_stem}"}]
            updated = self.set_frontmatter_sources(content, sources)
            remaining_raw_sources = [value for value in sources if value.startswith("raw/")]
            if page.parent.name in {"concepts", "entities"} and raw_path in original_sources and not remaining_raw_sources:
                page.unlink(missing_ok=True)
            elif raw_path in original_sources or updated != content:
                write_text(page, updated)
        source_file.unlink(missing_ok=True)
        (self.root / raw_path).unlink(missing_ok=True)
        self.analysis_path(digest).unlink(missing_ok=True)
        state = self.load_state()
        state["sources"].pop(digest, None)
        self.save_state(state)
        queue = self.load_queue()
        queue["tasks"] = [task for task in queue["tasks"] if task.get("digest") != digest]
        self.save_queue(queue)
        reviews = self.load_reviews()
        reviews["items"] = [item for item in reviews["items"] if item.get("raw_path") != raw_path]
        self.save_reviews(reviews)
        self.append_log("remove", Path(raw_path).stem, f"- 已删除归档资料：`{raw_path}`")
        self.rebuild_index()
        self.rebuild_overview()
        self.rebuild_search_index()
        return raw_path

    def bm25_search(self, query: str, limit: int) -> list[tuple[float, Path, str]]:
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        pages = self.wiki_pages()
        documents = [(path, read_text(path)) for path in pages]
        counters = [Counter(tokenize(content)) for _, content in documents]
        average_length = sum(sum(counter.values()) for counter in counters) / max(len(counters), 1)
        frequencies = Counter(token for counter in counters for token in counter)
        total = len(documents)
        scores: list[tuple[float, Path, str]] = []
        for (path, content), counter in zip(documents, counters):
            length = max(sum(counter.values()), 1)
            score = 0.0
            title_tokens = set(tokenize(page_title(content, path.stem)))
            for token in set(query_tokens):
                tf = counter[token]
                if not tf:
                    continue
                idf = math.log(1 + (total - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
                score += idf * (tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(average_length, 1))))
                if token in title_tokens:
                    score += 1.5
            if score:
                scores.append((score, path, compact(strip_frontmatter(content), 380)))
        return sorted(scores, key=lambda item: (-item[0], item[1].as_posix()))[:limit]

    def rebuild_search_index(self) -> bool:
        try:
            connection = sqlite3.connect(self.search_db_path)
            try:
                connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(path UNINDEXED, title, content, tokenize='unicode61')")
                connection.execute("DELETE FROM wiki_fts")
                for path in self.wiki_pages():
                    content = read_text(path)
                    connection.execute("INSERT INTO wiki_fts(path, title, content) VALUES (?, ?, ?)", (self.relative_wiki_path(path), page_title(content, path.stem), strip_frontmatter(content)))
                connection.commit()
            finally:
                connection.close()
            return True
        except sqlite3.Error as error:
            print(f"  SQLite FTS5 索引不可用，继续使用 BM25：{error}", file=sys.stderr)
            return False

    def fts_search(self, query: str, limit: int) -> list[tuple[float, Path, str]]:
        if not self.search_db_path.exists() and not self.rebuild_search_index():
            return []
        terms = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query)
        if not terms:
            return []
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        try:
            connection = sqlite3.connect(self.search_db_path)
            try:
                rows = connection.execute("SELECT path, bm25(wiki_fts) FROM wiki_fts WHERE wiki_fts MATCH ? ORDER BY bm25(wiki_fts) LIMIT ?", (expression, limit)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return []
        hits = []
        for relative, score in rows:
            path = self.wiki / str(relative)
            if path.is_file():
                hits.append((float(score), path, compact(strip_frontmatter(read_text(path)), 380)))
        return hits

    def search(self, query: str, limit: int) -> list[tuple[float, Path, str]]:
        bm25_hits = self.bm25_search(query, max(limit * 3, 20))
        fts_hits = self.fts_search(query, max(limit * 3, 20))
        ranked: dict[Path, float] = {}
        excerpts: dict[Path, str] = {}
        for hits in (bm25_hits, fts_hits):
            for rank, (_, path, excerpt) in enumerate(hits, 1):
                ranked[path] = ranked.get(path, 0.0) + 1 / (60 + rank)
                excerpts.setdefault(path, excerpt)
        return [(score, path, excerpts[path]) for path, score in sorted(ranked.items(), key=lambda item: (-item[1], item[0].as_posix()))[:limit]]

    def valid_answer_references(self, answer: str, paths: list[Path]) -> bool:
        allowed = {self.wiki_link(path).removesuffix(".md") for path in paths}
        cited = {reference.strip().removesuffix(".md") for reference in re.findall(r"\[(wiki/[^\]]+)\]", answer)}
        return bool(cited) and cited.issubset(allowed)

    def append_answer_evidence(self, answer: str, paths: list[Path]) -> str:
        evidence = "\n".join(f"- [{self.wiki_link(path)}]" for path in paths)
        return answer.rstrip() + "\n\n## 依据页面\n\n" + evidence

    def ask(self, question: str, args: argparse.Namespace) -> str:
        if not args.llm_url or not args.model:
            raise ValueError("ask 需要 --llm-url 和 --model，以便调用本地 OpenAI 兼容模型。")
        hits = self.search(question, args.top_k)
        if not hits:
            return "当前 Wiki 中没有足够的相关页面。请先导入资料或调整问题。"
        paths = [path for _, path, _ in hits]
        context = "\n\n".join(f"[{self.wiki_link(path)}]\n{read_text(path)[:5000]}" for path in paths)
        system = "你只能依据给定的 Wiki 页面回答。每个可验证结论都使用 [wiki/路径] 引用，且引用必须来自给定页面。资料不足时明确说明，不能编造。使用简体中文。"
        user = f"问题：{question}\n\nWiki 页面：\n{context}"
        answer = self.llm_request([{"role": "system", "content": system}, {"role": "user", "content": user}], args, temperature=0.2).strip()
        if not self.valid_answer_references(answer, paths):
            retry = f"你的上一回答缺少有效 [wiki/路径] 引用或引用越界。只可使用：{', '.join(self.wiki_link(path) for path in paths)}。\n\n上一回答：\n{answer}\n\n请修正后重答。"
            answer = self.llm_request([{"role": "system", "content": system}, {"role": "user", "content": user}, {"role": "user", "content": retry}], args, temperature=0.1).strip()
        if not self.valid_answer_references(answer, paths):
            answer = self.append_answer_evidence(answer, paths)
        if args.save:
            title = f"问答：{question}"
            path = self.wiki / "queries" / f"{today()}-{slug(question, 'query')}.md"
            source_links = [self.relative_wiki_path(item) for item in paths]
            body = frontmatter(title, "query", source_links) + f"# {title}\n\n## 回答\n\n{answer}\n\n## 检索页面\n\n" + "\n".join(f"- [[wiki/{item.removesuffix('.md')}]]" for item in source_links)
            write_text(path, body)
            self.append_log("query", question, f"- 已保存：[[{self.wiki_link(path)}]]")
        return answer

    def lint(self) -> tuple[list[str], list[str], list[str]]:
        pages = self.all_wiki_pages()
        known = {self.relative_wiki_path(path).removesuffix(".md") for path in pages}
        inbound = Counter()
        broken: list[str] = []
        missing_sources: list[str] = []
        for path in pages:
            relative = self.relative_wiki_path(path)
            content = read_text(path)
            for link in re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", content):
                target = link.strip().removesuffix(".md")
                vault_target = target.removeprefix("wiki/")
                candidates = {vault_target, (path.parent.relative_to(self.wiki) / target).as_posix()}
                found = next((item for item in candidates if item in known), None)
                if found:
                    inbound[found] += 1
                else:
                    broken.append(f"{relative} -> [[{link.strip()}]]")
            if "type: index" not in content and "type: log" not in content and "type: overview" not in content and "type: review_queue" not in content:
                sources = re.search(r"^sources:\s*\n((?:\s+-\s+.+\n?)*)", content, re.MULTILINE)
                if not sources or not sources.group(1).strip():
                    missing_sources.append(relative)
                else:
                    for line in sources.group(1).splitlines():
                        value = line.split("-", 1)[1].strip() if "-" in line else ""
                        try:
                            source_path = json.loads(value)
                        except json.JSONDecodeError:
                            source_path = value.strip('"\'')
                        if source_path.startswith("raw/"):
                            exists = (self.root / source_path).is_file()
                        elif source_path.startswith("wiki/"):
                            candidate = self.root / source_path
                            exists = (candidate if candidate.suffix else candidate.with_suffix(".md")).is_file()
                        elif source_path.split("/", 1)[0] in WIKI_DIRECTORIES:
                            candidate = self.wiki / source_path
                            exists = (candidate if candidate.suffix else candidate.with_suffix(".md")).is_file()
                        else:
                            exists = False
                        if source_path and not exists:
                            missing_sources.append(f"{relative} -> {source_path}")
        orphans = [
            item
            for item in sorted(known)
            if item not in {"index", "log", "overview", "reviews"}
            and item.split("/", 1)[0] not in {"sources", "queries"}
            and inbound[item] == 0
        ]
        return broken, orphans, missing_sources


def collect_sources(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    iterator = path.rglob("*") if recursive else path.glob("*")
    return sorted(item for item in iterator if item.is_file() and item.suffix.lower() in SOURCE_EXTENSIONS)


def scan_inbox_once(wiki: Wiki, path: Path, args: argparse.Namespace, observed: dict[Path, tuple[tuple[int, int], float, bool]], *, emit: bool = True) -> dict:
    """Queue and process one stable inbox scan; shared by CLI watch and the local control center."""
    path.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    current: set[Path] = set()
    queued = False
    for source in collect_sources(path, recursive=True):
        source = source.resolve()
        current.add(source)
        try:
            stat = source.stat()
        except OSError:
            continue
        signature = (stat.st_size, stat.st_mtime_ns)
        record = observed.get(source)
        if record is None or record[0] != signature:
            observed[source] = (signature, now, False)
            record = observed[source]
            if emit:
                print(f"检测到变更，等待写入完成：{source.relative_to(path.resolve())}")
        _, stable_since, handled = record
        if handled or now - stable_since < args.settle_seconds:
            continue
        try:
            task_id = wiki.enqueue_source(source)
        except OSError as error:
            if emit:
                print(f"无法入队，将重试：{source} ({error})", file=sys.stderr)
            continue
        observed[source] = (signature, stable_since, True)
        queued = queued or bool(task_id)
    observed_keys = set(observed)
    for source in observed_keys - current:
        observed.pop(source, None)
    result = wiki.process_queue(args) if queued or any(task.get("status") in {"pending", "failed"} for task in wiki.load_queue()["tasks"]) else {"completed": 0, "failed": 0, "skipped": 0, "applied": 0, "drafted": 0}
    return result


def watch_inbox(wiki: Wiki, path: Path, args: argparse.Namespace) -> int:
    """Import files once their size and modified time have been stable long enough."""
    path.mkdir(parents=True, exist_ok=True)
    observed: dict[Path, tuple[tuple[int, int], float, bool]] = {}
    print(f"正在监听：{path}")
    print(f"文件稳定 {args.settle_seconds:g} 秒后会自动归档；按 Ctrl+C 停止。")
    while True:
        result = scan_inbox_once(wiki, path, args, observed)
        if result.get("applied"):
            print("Wiki 索引和概览已更新。")
        if result.get("drafted"):
            print(f"已生成 {result['drafted']} 个草稿，可运行 draft list 查看。")
        if result["failed"]:
            print(f"有 {result['failed']} 个任务处理失败，可运行 queue status 查看详情。", file=sys.stderr)
        if args.once and all(record[2] for record in observed.values()):
            return 0
        time.sleep(args.interval)


WEB_ROOT = _ROOT / "web"

STATIC_CONTENT_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def render_control_index(control: "LocalControl") -> bytes:
    index_path = WEB_ROOT / "index.html"
    if not index_path.is_file():
        raise FileNotFoundError(f"缺少控制中心页面：{index_path}")
    with control.lock:
        sources = [item for item in control.wiki.status_summary()["sources"] if item.get("status") != "trashed"]
    options = "".join(
        f'<option value="{html.escape(str(item["raw_path"]), quote=True)}">{html.escape(str(item["title"]))}</option>'
        for item in sources
    )
    page = read_text(index_path).replace("__TOKEN__", control.token).replace(
        "__SOURCES__", options or '<option value="">暂无可移入资料</option>'
    )
    return page.encode("utf-8")


def serve_web_static(rel_path: str) -> tuple[str, bytes] | None:
    """Return (content_type, body) for a file under web/, or None if not found."""
    rel = Path(unquote(rel_path))
    if rel.is_absolute() or ".." in rel.parts:
        return None
    web_root = WEB_ROOT.resolve()
    target = (WEB_ROOT / rel).resolve()
    if web_root not in target.parents and target != web_root:
        return None
    if not target.is_file():
        return None
    suffix = target.suffix.lower()
    content_type = STATIC_CONTENT_TYPES.get(suffix, "application/octet-stream")
    return content_type, target.read_bytes()


class LocalControl:
    def __init__(self, wiki: Wiki, args: argparse.Namespace):
        self.wiki = wiki
        self.args = args
        self.instance_lock = InstanceLock(wiki.root)
        self.instance_lock.acquire()
        self.control_state = ControlState.load_or_create(wiki.root, args.port)
        self.token = self.control_state.token
        self.repository = Repository(wiki.root)
        wiki.repository = self.repository
        self.job_store = AcquisitionStore(self.repository)
        self.job_runner = JobRunner(wiki, args, self.job_store)
        self.job_runner.start()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.observed: dict[Path, tuple[tuple[int, int], float, bool]] = {}

    def start_watcher(self) -> None:
        if getattr(self.args, "no_watch", False):
            return
        path = (getattr(self.args, "path", None) or self.wiki.inbox).resolve()

        def worker() -> None:
            while not self.stop_event.is_set():
                try:
                    with self.lock:
                        scan_inbox_once(self.wiki, path, self.args, self.observed, emit=False)
                except Exception as error:
                    print(f"本地控制中心监听失败：{error}", file=sys.stderr)
                self.stop_event.wait(self.args.interval)

        threading.Thread(target=worker, name="llm-wiki-watch", daemon=True).start()


def make_control_handler(control: LocalControl) -> type[BaseHTTPRequestHandler]:
    class ControlHandler(BaseHTTPRequestHandler):
        server_version = "LocalLLMWiki/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, status: int, error: str) -> None:
            payload = {"error": error}
            if status == HTTPStatus.FORBIDDEN:
                payload = ApiError("unauthorised", error, retryable=False).to_dict()
            self.send_json(status, payload)

        def dispatch_v1_post(self, parsed, body: bytes) -> bool:
            try:
                header_map = {key: value for key, value in self.headers.items()}
                result = handle_v1_post(
                    parsed.path,
                    body,
                    header_map,
                    control.wiki,
                    control.args,
                    control.control_state,
                    control.job_runner,
                )
            except ApiError as error:
                status, payload = api_error_response(error)
                self.send_json(status, payload)
                return True
            if result is None:
                return False
            status, payload = result
            self.send_json(status, payload)
            return True

        def read_body(self) -> bytes:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 20 * 1024 * 1024:
                raise ValueError("请求过大。")
            return self.rfile.read(size) if size > 0 else b""

        def dispatch_v1_get(self, parsed) -> bool:
            try:
                result = handle_v1_get(
                    parsed.path,
                    parsed.query,
                    control.wiki,
                    control.args,
                    control.control_state,
                    authorised=self.authorised() if parsed.path != "/api/capabilities" else True,
                )
            except ApiError as error:
                status, payload = api_error_response(error)
                self.send_json(status, payload)
                return True
            if result is None:
                return False
            status, payload = result
            self.send_json(status, payload)
            return True

        def read_json(self) -> dict:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 2 * 1024 * 1024:
                raise ValueError("请求过大。")
            value = json.loads(self.rfile.read(size).decode("utf-8") or "{}")
            if not isinstance(value, dict):
                raise ValueError("请求格式无效。")
            return value

        def authorised(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-LLM-Wiki-Token", ""), control.token)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if self.dispatch_v1_get(parsed):
                    return
                if parsed.path.startswith("/static/"):
                    static = serve_web_static(parsed.path.removeprefix("/static/"))
                    if static is None:
                        self.send_error_json(404, "未找到资源。")
                        return
                    content_type, body = static
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path == "/":
                    body = render_control_index(control)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                with control.lock:
                    if parsed.path == "/api/status":
                        payload = control.wiki.status_summary()
                        payload["model_ready"] = bool(control.args.llm_url and control.args.model)
                        self.send_json(200, payload)
                        return
                    if parsed.path == "/api/drafts":
                        self.send_json(200, [item for item in control.wiki.list_drafts("draft")])
                        return
                    if parsed.path.startswith("/api/drafts/"):
                        run_id = parsed.path.removeprefix("/api/drafts/")
                        manifest = control.wiki.load_draft(run_id)
                        self.send_json(200, {**manifest, "diffs": control.wiki.draft_diff(manifest)})
                        return
                    if parsed.path == "/api/search":
                        query = parse_qs(parsed.query).get("q", [""])[0]
                        hits = control.wiki.search(query, 8)
                        self.send_json(200, [{"score": round(score, 3), "path": control.wiki.relative_wiki_path(path), "excerpt": excerpt} for score, path, excerpt in hits])
                        return
                    if parsed.path == "/api/reviews":
                        queue = parse_qs(parsed.query).get("queue", [""])[0]
                        if queue not in {"", "facts", "research"}:
                            raise ValueError("审核队列无效。")
                        items = [item for item in control.wiki.load_reviews()["items"] if item.get("status") == "open"]
                        if queue:
                            items = [item for item in items if control.wiki.review_queue(item) == queue]
                        self.send_json(200, items)
                        return
                    if parsed.path.startswith("/api/reviews/"):
                        self.send_json(200, control.wiki.review_detail(parsed.path.removeprefix("/api/reviews/")))
                        return
                    if parsed.path == "/api/trash":
                        self.send_json(200, control.wiki.list_trash())
                        return
                self.send_error_json(404, "未找到资源。")
            except ValueError as error:
                self.send_error_json(404, str(error))
            except Exception as error:
                self.send_error_json(500, str(error))

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/v1/"):
                    if not self.authorised():
                        self.send_error_json(403, "请求令牌无效。")
                        return
                    with control.lock:
                        if self.dispatch_v1_post(parsed, self.read_body()):
                            return
                if parsed.path == "/action/trash":
                    size = int(self.headers.get("Content-Length", "0"))
                    form = parse_qs(self.rfile.read(size).decode("utf-8"))
                    form_token = form.get("token", [""])[0]
                    if not secrets.compare_digest(form_token, control.token):
                        self.send_error_json(403, "请求令牌无效。")
                        return
                    with control.lock:
                        control.wiki.trash_source(form.get("target", [""])[0])
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return
                if not self.authorised():
                    self.send_error_json(403, "请求令牌无效。")
                    return
                with control.lock:
                    if parsed.path == "/api/inbox":
                        raw_name = unquote(self.headers.get("X-Filename", ""))
                        name = Path(raw_name).name
                        if not name or Path(name).suffix.lower() not in SOURCE_EXTENSIONS:
                            raise ValueError("只支持 Markdown 或 TXT 文件。")
                        size = int(self.headers.get("Content-Length", "0"))
                        if size <= 0 or size > 20 * 1024 * 1024:
                            raise ValueError("文件大小必须在 1 B 到 20 MB 之间。")
                        target = control.wiki.inbox / name
                        target.write_bytes(self.rfile.read(size))
                        self.send_json(201, {"name": name})
                        return
                    if parsed.path.startswith("/api/drafts/"):
                        parts = parsed.path.split("/")
                        if len(parts) != 5 or parts[4] not in {"accept", "discard"}:
                            raise ValueError("草稿操作无效。")
                        manifest = control.wiki.apply_draft(parts[3]) if parts[4] == "accept" else control.wiki.discard_draft(parts[3])
                        self.send_json(200, manifest)
                        return
                    if parsed.path == "/api/rebuild":
                        control.wiki.rebuild_derived()
                        self.send_json(200, {"status": "rebuilt"})
                        return
                    if parsed.path == "/api/ask":
                        data = self.read_json()
                        question = str(data.get("question", "")).strip()
                        if not question:
                            raise ValueError("问题不能为空。")
                        control.args.top_k = 6
                        control.args.save = False
                        self.send_json(200, {"answer": control.wiki.ask(question, control.args)})
                        return
                    if parsed.path.startswith("/api/reviews/"):
                        review_id = parsed.path.removeprefix("/api/reviews/")
                        data = self.read_json()
                        status = str(data.get("status", ""))
                        note = str(data.get("resolution_note", ""))
                        if status not in {"open", "resolved"} or not control.wiki.set_review_status(review_id, status, note):
                            raise ValueError("审核项不存在或状态无效。")
                        self.send_json(200, {"id": review_id, "status": status})
                        return
                    if parsed.path == "/api/trash":
                        target = str(self.read_json().get("target", ""))
                        self.send_json(200, control.wiki.trash_source(target))
                        return
                    if parsed.path.startswith("/api/trash/") and parsed.path.endswith("/restore"):
                        digest = parsed.path.removeprefix("/api/trash/").removesuffix("/restore")
                        self.send_json(200, control.wiki.restore_source(digest))
                        return
                    if parsed.path == "/api/aliases":
                        data = self.read_json()
                        path = control.wiki.add_topic_alias(str(data.get("kind", "")), str(data.get("target", "")), str(data.get("alias", "")))
                        self.send_json(200, {"path": control.wiki.relative_wiki_path(path)})
                        return
                    if parsed.path == "/api/merge":
                        data = self.read_json()
                        path = control.wiki.merge_topic_pages(str(data.get("kind", "")), str(data.get("source", "")), str(data.get("target", "")))
                        self.send_json(200, {"path": control.wiki.relative_wiki_path(path)})
                        return
                self.send_error_json(404, "未找到操作。")
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
                self.send_error_json(400, str(error))
            except Exception as error:
                self.send_error_json(500, str(error))

    return ControlHandler


def serve_control_center(wiki: Wiki, args: argparse.Namespace) -> int:
    if args.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("本地控制中心只能绑定 127.0.0.1 或 localhost。")
    control = LocalControl(wiki, args)
    control.start_watcher()
    server = ThreadingHTTPServer((args.host, args.port), make_control_handler(control))
    address = f"http://{args.host}:{args.port}/"
    print(f"本地控制中心：{address}")
    print("按 Ctrl+C 停止。")
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n本地控制中心已停止。")
    finally:
        control.stop_event.set()
        control.job_runner.stop()
        control.instance_lock.release()
        server.server_close()
    return 0


def common_llm_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--llm-url", help="本地 OpenAI 兼容的 /v1/chat/completions 地址")
    parser.add_argument("--model", help="模型名称，例如 qwen3:8b")
    parser.add_argument("--api-key", default=os.environ.get("LLM_WIKI_API_KEY", ""), help="Bearer API key，默认读取 LLM_WIKI_API_KEY")
    parser.add_argument("--timeout", type=int, default=120, help="模型请求超时秒数，默认 120")


def apply_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true", help="跳过草稿确认，直接写入 Wiki")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="维护本地 Markdown LLM Wiki")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="知识库根目录")
    subcommands = parser.add_subparsers(dest="command", required=True)
    ingest = subcommands.add_parser("ingest", help="导入 Markdown/TXT 原始资料")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--recursive", action="store_true", help="递归导入目录")
    ingest.add_argument("--max-tokens", type=int, default=1800, help="模型分析的最大输出 token")
    common_llm_options(ingest)
    apply_option(ingest)
    search = subcommands.add_parser("search", help="SQLite FTS5 + BM25 融合搜索 Wiki")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=8)
    search.add_argument("--rebuild-index", action="store_true", help="搜索前重建 SQLite FTS5 索引")
    ask = subcommands.add_parser("ask", help="基于 Wiki 页面向本地模型提问")
    ask.add_argument("question")
    ask.add_argument("--top-k", type=int, default=6)
    ask.add_argument("--save", action="store_true", help="将回答保存到 wiki/queries")
    common_llm_options(ask)
    watch = subcommands.add_parser("watch", help="监听 raw/inbox，自动归档新资料")
    watch.add_argument("--path", type=Path, help="默认监听 raw/inbox")
    watch.add_argument("--interval", type=float, default=2, help="扫描间隔秒数，默认 2")
    watch.add_argument("--settle-seconds", type=float, default=4, help="文件稳定多久后导入，默认 4")
    watch.add_argument("--once", action="store_true", help="处理当前稳定文件后退出，用于手动扫描或验证")
    watch.add_argument("--max-tokens", type=int, default=1800, help="模型分析的最大输出 token")
    common_llm_options(watch)
    watch.add_argument("--auto-accept", action="store_true", help="模型生成后直接应用，不保留草稿")
    refine = subcommands.add_parser("refine", help="用模型重新提炼 raw/sources 中的已归档资料")
    refine.add_argument("path", type=Path, nargs="?", help="默认处理全部 raw/sources 资料")
    refine.add_argument("--max-tokens", type=int, default=1800, help="模型分析的最大输出 token")
    common_llm_options(refine)
    apply_option(refine)
    synthesize = subcommands.add_parser("synthesize", help="基于多份资料生成跨资料综合页面")
    synthesize.add_argument("topic", nargs="?", default="", help="可选主题；为空时综合所有资料摘要")
    synthesize.add_argument("--top-k", type=int, default=8, help="最多综合的资料摘要数")
    synthesize.add_argument("--max-tokens", type=int, default=2200, help="模型生成的最大输出 token")
    common_llm_options(synthesize)
    apply_option(synthesize)
    remove = subcommands.add_parser("remove", help="级联删除一份已归档资料及其派生页面")
    remove.add_argument("target", help="raw/sources 路径或 wiki/sources 页面路径")
    remove.add_argument("--yes", action="store_true", help="确认执行删除")
    review = subcommands.add_parser("review", help="查看和处理模型待审核项")
    review_subcommands = review.add_subparsers(dest="review_command", required=True)
    review_list = review_subcommands.add_parser("list", help="列出审核项")
    review_list.add_argument("--status", choices=("open", "resolved", "all"), default="open")
    review_list.add_argument("--queue", choices=("facts", "research", "all"), default="all", help="facts 仅显示带原文引句的事实；research 显示待补充")
    for action, status in (("resolve", "resolved"), ("reopen", "open")):
        review_action = review_subcommands.add_parser(action, help=f"标记审核项为 {status}")
        review_action.add_argument("id")
    queue = subcommands.add_parser("queue", help="查看或处理持久导入队列")
    queue_subcommands = queue.add_subparsers(dest="queue_command", required=True)
    queue_subcommands.add_parser("status", help="列出队列任务")
    queue_process = queue_subcommands.add_parser("process", help="处理待处理或失败任务")
    queue_process.add_argument("--max-tokens", type=int, default=1800, help="模型分析的最大输出 token")
    queue_process.add_argument("--max-attempts", type=int, default=MAX_QUEUE_ATTEMPTS)
    common_llm_options(queue_process)
    apply_option(queue_process)
    queue_retry = queue_subcommands.add_parser("retry", help="重置一个失败任务")
    queue_retry.add_argument("id")
    draft = subcommands.add_parser("draft", help="查看、应用或丢弃模型草稿")
    draft_subcommands = draft.add_subparsers(dest="draft_command", required=True)
    draft_list = draft_subcommands.add_parser("list", help="列出草稿")
    draft_list.add_argument("--status", choices=("draft", "applied", "discarded", "recovered", "all"), default="draft")
    draft_show = draft_subcommands.add_parser("show", help="显示草稿摘要和差异")
    draft_show.add_argument("id")
    for action in ("accept", "discard"):
        draft_action = draft_subcommands.add_parser(action, help=f"{action} 一个草稿")
        draft_action.add_argument("id")
    trash = subcommands.add_parser("trash", help="移入回收站或恢复资料")
    trash_subcommands = trash.add_subparsers(dest="trash_command", required=True)
    trash_subcommands.add_parser("list", help="列出回收站")
    trash_move = trash_subcommands.add_parser("move", help="将一份资料移入回收站")
    trash_move.add_argument("target")
    trash_restore = trash_subcommands.add_parser("restore", help="恢复一份资料")
    trash_restore.add_argument("digest")
    topic = subcommands.add_parser("topic", help="处理概念和实体的别名或显式合并")
    topic_subcommands = topic.add_subparsers(dest="topic_command", required=True)
    topic_alias = topic_subcommands.add_parser("alias", help="为页面添加别名")
    topic_alias.add_argument("kind", choices=("concepts", "entities"))
    topic_alias.add_argument("target")
    topic_alias.add_argument("alias")
    topic_merge = topic_subcommands.add_parser("merge", help="显式合并两个页面")
    topic_merge.add_argument("kind", choices=("concepts", "entities"))
    topic_merge.add_argument("source")
    topic_merge.add_argument("target")
    status = subcommands.add_parser("status", help="显示收件箱、草稿、审核和健康状态")
    status.add_argument("--json", action="store_true", help="以 JSON 输出")
    serve = subcommands.add_parser("serve", help="启动本机控制中心和收件箱监听")
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--path", type=Path, help="默认监听 raw/inbox")
    serve.add_argument("--interval", type=float, default=2, help="扫描间隔秒数，默认 2")
    serve.add_argument("--settle-seconds", type=float, default=4, help="文件稳定多久后入队，默认 4")
    serve.add_argument("--max-tokens", type=int, default=1800, help="模型分析的最大输出 token")
    serve.add_argument("--auto-accept", action="store_true", help="模型生成后直接应用，不保留草稿")
    serve.add_argument("--no-watch", action="store_true", help="不启动收件箱监听")
    serve.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    common_llm_options(serve)
    subcommands.add_parser("rebuild", help="重建 Wiki 导航、概览和搜索索引")
    subcommands.add_parser("lint", help="检查 Wiki 链接、孤儿页和来源")
    mcp = subcommands.add_parser("mcp", help="启动薄 MCP 服务（只读转发 loopback API）")
    mcp.add_argument("--http", action="store_true", help="使用 loopback HTTP 而非 stdin/stdout")
    mcp.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    mcp.add_argument("--port", type=int, default=8766, help="HTTP 模式端口，默认 8766")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wiki = Wiki(args.root)
    wiki.ensure_layout()
    from llm_wiki.config import apply_config_to_args

    apply_config_to_args(args, wiki.root)
    if args.command == "ingest":
        path = args.path.resolve()
        if not path.exists():
            print(f"找不到路径：{path}", file=sys.stderr)
            return 2
        sources = collect_sources(path, args.recursive)
        if not sources:
            print("没有找到可导入的 Markdown/TXT 文件。", file=sys.stderr)
            return 2
        try:
            count = sum(wiki.ingest(source, args) for source in sources)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
            print(f"导入失败：{error}", file=sys.stderr)
            return 1
        if not args.llm_url or args.apply:
            wiki.rebuild_index()
            wiki.rebuild_overview()
            wiki.rebuild_search_index()
        print(f"完成：处理 {count} 份资料，跳过 {len(sources) - count} 份。")
        return 0
    if args.command == "search":
        if args.rebuild_index:
            wiki.rebuild_search_index()
        hits = wiki.search(args.query, args.top_k)
        if not hits:
            print("没有命中 Wiki 页面。")
            return 0
        for number, (score, path, excerpt) in enumerate(hits, 1):
            print(f"{number}. {wiki.relative_wiki_path(path)}  score={score:.3f}\n   {excerpt}\n")
        return 0
    if args.command == "ask":
        try:
            answer = wiki.ask(args.question, args)
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
            print(f"问答失败：{error}", file=sys.stderr)
            return 1
        if args.save:
            wiki.rebuild_index()
        print(answer)
        return 0
    if args.command == "watch":
        watch_path = (args.path or wiki.inbox).resolve()
        if args.interval <= 0 or args.settle_seconds < 0:
            print("--interval 必须大于 0，--settle-seconds 不能小于 0。", file=sys.stderr)
            return 2
        try:
            return watch_inbox(wiki, watch_path, args)
        except KeyboardInterrupt:
            print("\n监听已停止。")
            return 0
    if args.command == "refine":
        if not args.llm_url or not args.model:
            print("refine 需要 --llm-url 和 --model。", file=sys.stderr)
            return 2
        path = (args.path or wiki.raw).resolve()
        if not path.exists():
            print(f"找不到路径：{path}", file=sys.stderr)
            return 2
        sources = collect_sources(path, recursive=True)
        if not sources:
            print("没有找到可重新提炼的 Markdown/TXT 归档资料。")
            return 0
        try:
            count = sum(wiki.refine(source, args) for source in sources)
        except (HTTPError, URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
            print(f"重新提炼失败：{error}", file=sys.stderr)
            return 1
        if args.apply:
            wiki.rebuild_index()
            wiki.rebuild_overview()
            wiki.rebuild_search_index()
        print(f"完成：已处理 {count} 份资料。")
        return 0
    if args.command == "synthesize":
        try:
            path = wiki.synthesize(args.topic, args, args.top_k)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
            print(f"综合失败：{error}", file=sys.stderr)
            return 1
        print(f"已生成综合页：{path}")
        return 0
    if args.command == "remove":
        if not args.yes:
            print("remove 会删除原始归档、派生摘要和独占概念/实体页；请加 --yes 确认。", file=sys.stderr)
            return 2
        try:
            raw_path = wiki.remove_source(args.target)
        except ValueError as error:
            print(f"删除失败：{error}", file=sys.stderr)
            return 1
        print(f"已级联删除：{raw_path}")
        return 0
    if args.command == "review":
        if args.review_command == "list":
            reviews = wiki.load_reviews()["items"]
            items = reviews if args.status == "all" else [item for item in reviews if item.get("status") == args.status]
            if args.queue != "all":
                items = [item for item in items if wiki.review_queue(item) == args.queue]
            for item in items:
                evidence = f"\n  证据：{item.get('evidence_anchor')} {item.get('evidence_quote')}" if item.get("evidence_quote") else ""
                print(f"{item['id']}  {item.get('status')}  {item.get('kind')}  {item.get('title')}\n  {item.get('text')}\n  {item.get('raw_path')}{evidence}\n")
            print(f"共 {len(items)} 项。")
            return 0
        status = "resolved" if args.review_command == "resolve" else "open"
        if not wiki.set_review_status(args.id, status):
            print("找不到审核项。", file=sys.stderr)
            return 1
        print(f"审核项已标记为 {status}：{args.id}")
        return 0
    if args.command == "queue":
        if args.queue_command == "status":
            tasks = wiki.load_queue()["tasks"]
            for task in tasks:
                print(f"{task['id']}  {task.get('status')}  attempts={task.get('attempts', 0)}\n  {task.get('source')}\n  {task.get('error', '')}\n")
            print(f"共 {len(tasks)} 项。")
            return 0
        if args.queue_command == "retry":
            if not wiki.retry_queue_task(args.id):
                print("找不到队列任务。", file=sys.stderr)
                return 1
            print(f"队列任务已重置：{args.id}")
            return 0
        result = wiki.process_queue(args, args.max_attempts)
        print(f"完成={result['completed']} 已应用={result['applied']} 草稿={result['drafted']} 跳过={result['skipped']} 失败={result['failed']}")
        return 1 if result["failed"] else 0
    if args.command == "draft":
        if args.draft_command == "list":
            drafts = wiki.list_drafts(args.status)
            for item in drafts:
                summary = item.get("summary", {})
                print(f"{item['id']}  {item.get('status')}  {item.get('title')}\n  新增={summary.get('created', 0)} 修改={summary.get('modified', 0)} 审核项={summary.get('review_items', 0)}\n")
            print(f"共 {len(drafts)} 项。")
            return 0
        if args.draft_command == "show":
            try:
                manifest = wiki.load_draft(args.id)
            except ValueError as error:
                print(str(error), file=sys.stderr)
                return 1
            print(json.dumps({**manifest, "diffs": wiki.draft_diff(manifest)}, ensure_ascii=False, indent=2))
            return 0
        try:
            manifest = wiki.apply_draft(args.id) if args.draft_command == "accept" else wiki.discard_draft(args.id)
        except (ValueError, OSError, RuntimeError) as error:
            print(f"草稿操作失败：{error}", file=sys.stderr)
            return 1
        print(f"草稿已{ '应用' if args.draft_command == 'accept' else '丢弃' }：{manifest['id']}")
        return 0
    if args.command == "trash":
        if args.trash_command == "list":
            items = wiki.list_trash()
            for item in items:
                print(f"{item['digest']}  {item.get('title')}\n  {item.get('raw_path')}\n")
            print(f"共 {len(items)} 项。")
            return 0
        try:
            item = wiki.trash_source(args.target) if args.trash_command == "move" else wiki.restore_source(args.digest)
        except ValueError as error:
            print(f"回收站操作失败：{error}", file=sys.stderr)
            return 1
        print(f"已{ '移入回收站' if args.trash_command == 'move' else '恢复' }：{item.get('raw_path', '')}")
        return 0
    if args.command == "topic":
        try:
            path = wiki.add_topic_alias(args.kind, args.target, args.alias) if args.topic_command == "alias" else wiki.merge_topic_pages(args.kind, args.source, args.target)
        except ValueError as error:
            print(f"主题操作失败：{error}", file=sys.stderr)
            return 1
        print(f"已更新：{wiki.relative_wiki_path(path)}")
        return 0
    if args.command == "status":
        payload = wiki.status_summary()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"收件箱：{len(payload['inbox'])}")
            print(f"队列：待处理 {payload['queue']['pending']}，失败 {payload['queue']['failed']}")
            print(f"草稿：待确认 {payload['drafts']['draft']}")
            print(f"事实审核：待处理 {payload['reviews']['open']}")
            print(f"健康：断链 {payload['health']['broken_links']}，孤儿页 {payload['health']['orphan_pages']}，缺失来源 {payload['health']['missing_sources']}")
        return 0
    if args.command == "serve":
        if args.interval <= 0 or args.settle_seconds < 0 or args.port <= 0 or args.port > 65535:
            print("serve 参数无效。", file=sys.stderr)
            return 2
        try:
            return serve_control_center(wiki, args)
        except (OSError, ValueError) as error:
            print(f"启动控制中心失败：{error}", file=sys.stderr)
            return 1
    if args.command == "rebuild":
        wiki.rebuild_derived()
        print("已重建 Wiki 导航、概览和搜索索引。")
        return 0
    if args.command == "mcp":
        from llm_wiki.mcp_server import run_http, run_stdio

        if args.port <= 0 or args.port > 65535:
            print("mcp 端口无效。", file=sys.stderr)
            return 2
        if args.http:
            print(f"LLM Wiki MCP HTTP 监听 {args.host}:{args.port}", file=sys.stderr)
            return run_http(wiki.root, args.host, args.port)
        return run_stdio(wiki.root)
    broken, orphans, missing_sources = wiki.lint()
    print(f"断链：{len(broken)}")
    for item in broken:
        print(f"- {item}")
    print(f"孤儿页面：{len(orphans)}")
    for item in orphans:
        print(f"- {item}")
    print(f"缺失来源：{len(missing_sources)}")
    for item in missing_sources:
        print(f"- {item}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
