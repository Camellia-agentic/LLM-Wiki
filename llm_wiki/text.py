"""Pure text, YAML frontmatter, and JSON helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

PAGE_TYPES = {
    "concepts": "concept",
    "entities": "entity",
    "sources": "source_summary",
}


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
        return match.group(1).strip().strip("\"'")
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def strip_frontmatter(content: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL)


def first_heading(content: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def compact(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
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
