"""Markdown document chunking with heading paths and line anchors."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


@dataclass(frozen=True)
class Chunk:
    id: str
    heading_path: list[str]
    start_line: int
    end_line: int
    content: str
    content_digest: str


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _heading_path(stack: list[tuple[int, str]]) -> list[str]:
    return [title for _, title in stack]


def _paragraph_parts(text: str) -> list[str]:
    """Split text into paragraph or fenced-code parts without breaking fences."""
    lines = text.split("\n")
    parts: list[str] = []
    current: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in lines:
        if in_fence:
            current.append(line)
            if line.strip().startswith(fence_marker):
                in_fence = False
                parts.append("\n".join(current))
                current = []
            continue

        fence_match = FENCE_RE.match(line.strip())
        if fence_match:
            if current:
                parts.append("\n".join(current))
                current = []
            in_fence = True
            fence_marker = fence_match.group(1)
            current = [line]
            continue

        if not line.strip() and current:
            parts.append("\n".join(current))
            current = []
            continue

        current.append(line)

    if current:
        parts.append("\n".join(current))
    return [part for part in parts if part.strip()]


def _split_into_sections(lines: list[str]) -> list[tuple[list[str], int, int, str]]:
    sections: list[tuple[list[str], int, int, str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    section_start = 1
    in_fence = False
    fence_marker = ""

    def flush(end_line: int) -> None:
        nonlocal current_lines, section_start
        if current_lines or not sections:
            content = "\n".join(current_lines)
            sections.append((_heading_path(heading_stack), section_start, end_line, content))
        current_lines = []
        section_start = end_line + 1

    for index, line in enumerate(lines, start=1):
        if in_fence:
            current_lines.append(line)
            if line.strip().startswith(fence_marker):
                in_fence = False
            continue

        fence_match = FENCE_RE.match(line.strip())
        if fence_match:
            in_fence = True
            fence_marker = fence_match.group(1)
            current_lines.append(line)
            continue

        heading_match = HEADING_RE.match(line)
        if heading_match:
            if current_lines:
                flush(index - 1)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            current_lines = [line]
            section_start = index
            continue

        current_lines.append(line)

    flush(len(lines))
    return sections


def _line_offset(base_line: int, full_text: str, part_text: str) -> tuple[int, int]:
    if not part_text:
        return base_line, base_line
    start = full_text.find(part_text)
    if start < 0:
        return base_line, base_line + part_text.count("\n")
    prefix = full_text[:start]
    line_count = part_text.count("\n")
    return base_line + prefix.count("\n"), base_line + prefix.count("\n") + line_count


def _expand_section(
    heading_path: list[str],
    start_line: int,
    end_line: int,
    content: str,
    target_size: int,
) -> list[tuple[list[str], int, int, str]]:
    if len(content) <= target_size:
        return [(heading_path, start_line, end_line, content)]

    parts = _paragraph_parts(content)
    if len(parts) <= 1:
        return [(heading_path, start_line, end_line, content)]

    expanded: list[tuple[list[str], int, int, str]] = []
    cursor = 0
    for part in parts:
        part_start, part_end = _line_offset(start_line, content, content[cursor:])
        if cursor:
            part_start, part_end = _line_offset(start_line, content, part)
        expanded.append((heading_path, part_start, part_end, part))
        cursor += len(part) + 2
    return expanded


def _pack_pieces(
    pieces: list[tuple[list[str], int, int, str]],
    target_size: int,
) -> list[tuple[list[str], int, int, str]]:
    if not pieces:
        return []

    packed: list[tuple[list[str], int, int, str]] = []
    current_path: list[str] = []
    current_start = 0
    current_end = 0
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_path
        if not current_parts:
            return
        content = "\n\n".join(current_parts)
        packed.append((list(current_path), current_start, current_end, content))
        current_parts = []

    for heading_path, start_line, end_line, content in pieces:
        if not current_parts:
            current_path = heading_path
            current_start = start_line
            current_end = end_line
            current_parts = [content]
            continue

        candidate = "\n\n".join([*current_parts, content])
        if len(candidate) <= target_size:
            current_parts.append(content)
            current_end = end_line
            if len(heading_path) > len(current_path):
                current_path = heading_path
        else:
            flush()
            current_path = heading_path
            current_start = start_line
            current_end = end_line
            current_parts = [content]

    flush()
    return packed


def _apply_overlap(
    chunks: list[tuple[list[str], int, int, str]],
    overlap: int,
) -> list[tuple[list[str], int, int, str]]:
    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    merged: list[tuple[list[str], int, int, str]] = [chunks[0]]
    for heading_path, start_line, end_line, content in chunks[1:]:
        previous = merged[-1][3]
        prefix = previous[-overlap:] if len(previous) > overlap else previous
        if prefix.strip():
            content = prefix.rstrip() + "\n\n" + content.lstrip()
        merged.append((heading_path, start_line, end_line, content))
    return merged


def chunk_document(text: str, *, target_size: int = 8000, overlap: int = 200) -> list[Chunk]:
    """Split *text* into semantic chunks with heading paths and 1-based line numbers."""
    text = _normalise(text)
    if not text.strip():
        return []

    lines = text.split("\n")
    sections = _split_into_sections(lines)

    pieces: list[tuple[list[str], int, int, str]] = []
    for heading_path, start_line, end_line, content in sections:
        pieces.extend(_expand_section(heading_path, start_line, end_line, content, target_size))

    packed = _pack_pieces(pieces, target_size)
    packed = _apply_overlap(packed, overlap)

    result: list[Chunk] = []
    for index, (heading_path, start_line, end_line, content) in enumerate(packed, start=1):
        result.append(
            Chunk(
                id=f"chunk_{index:04d}",
                heading_path=list(heading_path),
                start_line=max(1, start_line),
                end_line=max(start_line, end_line),
                content=content,
                content_digest=_content_digest(content),
            )
        )
    return result
