"""Wiki navigation graph, semantic relations, and graph delta."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from llm_wiki.relations import (
    SEMANTIC_PREDICATES,
    normalise_predicate,
    parse_page_relations,
    parse_relations_section,
)
from llm_wiki.text import read_text, strip_frontmatter

WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
SKIP_PAGES = {"index", "log", "overview", "reviews"}
WIKI_SECTIONS = {"sources", "concepts", "entities", "queries", "synthesis"}
NAVIGATION_EDGE_KINDS = frozenset({"references", "supported_by"})
SYSTEM_PAGE_IDS = frozenset(
    {
        "index",
        "log",
        "overview",
        "reviews",
    }
)


@dataclass
class PageContext:
    page_id: str
    sources: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)
    outlinks: list[str] = field(default_factory=list)


def parse_wikilinks(content: str) -> list[str]:
    """Return normalised wikilink targets from Markdown content."""
    links: list[str] = []
    seen: set[str] = set()
    for match in WIKI_LINK_RE.finditer(content):
        target = match.group(1).strip().removesuffix(".md")
        if target.startswith("wiki/"):
            target = target.removeprefix("wiki/")
        if not target or target in seen:
            continue
        seen.add(target)
        links.append(target)
    return links


def _frontmatter_sources(content: str) -> list[str]:
    header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
    if not header:
        return []
    block = re.search(r"^sources:\n((?:  - .+\n?)*)", header.group(1), re.MULTILINE)
    if not block:
        return []
    values: list[str] = []
    for line in block.group(1).splitlines():
        value = line.removeprefix("  - ").strip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value.strip("\"'")
        if parsed:
            values.append(str(parsed))
    return values


def _page_id_from_path(path: Path, wiki_root: Path) -> str:
    relative = path.relative_to(wiki_root).as_posix()
    return relative.removesuffix(".md")


def _resolve_target(target: str, source_page_id: str, known: set[str]) -> str | None:
    candidates = {target, target.removeprefix("wiki/")}
    if "/" not in target and source_page_id:
        section = source_page_id.split("/", 1)[0]
        candidates.add(f"{section}/{target}")
    for candidate in candidates:
        if candidate in known:
            return candidate
    return None


def _edge_key(edge: dict[str, object]) -> tuple[str, ...]:
    return (
        str(edge.get("from", "")),
        str(edge.get("to", "")),
        str(edge.get("kind", "")),
        str(edge.get("predicate", "")),
        str(edge.get("source", "")),
        str(edge.get("evidence_quote", "")),
    )


def _is_system_page(page_id: str) -> bool:
    stem = page_id.split("/", 1)[0] if "/" in page_id else page_id
    return page_id in SYSTEM_PAGE_IDS or stem in SYSTEM_PAGE_IDS


def _collect_broken_links(edges: list[dict[str, object]], known: set[str]) -> list[dict[str, str]]:
    broken: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("broken"):
            key = (str(edge.get("from", "")), str(edge.get("to", "")), str(edge.get("kind", "")))
            if key not in seen:
                seen.add(key)
                broken.append(
                    {
                        "from": str(edge.get("from", "")),
                        "to": str(edge.get("to", "")),
                        "kind": str(edge.get("kind", "")),
                    }
                )
            continue
        target = str(edge.get("to", ""))
        if target.startswith("raw/"):
            continue
        if target not in known and str(edge.get("kind", "")) in {"references", *SEMANTIC_PREDICATES}:
            key = (str(edge.get("from", "")), target, str(edge.get("kind", "")))
            if key not in seen:
                seen.add(key)
                broken.append({"from": str(edge.get("from", "")), "to": target, "kind": str(edge.get("kind", ""))})
    return broken


def _semantic_edges_for_page(
    page_id: str,
    content: str,
    known: set[str],
) -> list[dict[str, object]]:
    edges: list[dict[str, object]] = []
    relations = parse_page_relations(content)
    if not relations:
        body = strip_frontmatter(content)
        relations = parse_relations_section(body)
    for relation in relations:
        target = str(relation.get("target", "")).strip().removeprefix("wiki/")
        if not target:
            continue
        predicate = normalise_predicate(str(relation.get("predicate", "related_to")))
        edge: dict[str, object] = {
            "from": page_id,
            "to": target,
            "kind": predicate,
            "predicate": predicate,
        }
        source = str(relation.get("source", "")).strip()
        if source:
            edge["source"] = source
        evidence_quote = str(relation.get("evidence_quote", "")).strip()
        if evidence_quote:
            edge["evidence_quote"] = evidence_quote
        evidence_anchor = str(relation.get("evidence_anchor", "")).strip()
        if evidence_anchor:
            edge["evidence_anchor"] = evidence_anchor
        confidence = str(relation.get("confidence", "")).strip()
        if confidence:
            edge["confidence"] = confidence
        verification = str(relation.get("verification", "")).strip()
        if verification:
            edge["verification"] = verification
        if target not in known and not target.startswith("raw/"):
            edge["broken"] = True
        edges.append(edge)
    return edges


def build_navigation_graph(wiki_root: Path) -> dict[str, object]:
    """Build a navigation graph from wikilinks and frontmatter sources."""
    return _build_graph(wiki_root)


def build_semantic_graph(
    wiki_root: Path,
    *,
    page_contents: dict[str, str] | None = None,
    include_system_pages: bool = False,
) -> dict[str, object]:
    """Build navigation + semantic relation edges from wiki pages."""
    return _build_graph(
        wiki_root,
        page_contents=page_contents,
        include_semantic=True,
        include_system_pages=include_system_pages,
    )


def _build_graph(
    wiki_root: Path,
    *,
    page_contents: dict[str, str] | None = None,
    include_semantic: bool = False,
    include_system_pages: bool = False,
) -> dict[str, object]:
    wiki_root = wiki_root.resolve()
    pages: dict[str, dict[str, object]] = {}
    edges: list[dict[str, object]] = []

    if not wiki_root.is_dir():
        return {"pages": {}, "edges": []}

    md_files = sorted(wiki_root.rglob("*.md"))
    known = {_page_id_from_path(path, wiki_root) for path in md_files}
    if page_contents:
        for relative in page_contents:
            page_id = relative.removesuffix(".md")
            known.add(page_id)

    outlinks_map: dict[str, list[str]] = {page_id: [] for page_id in known}
    backlinks_map: dict[str, list[str]] = {page_id: [] for page_id in known}

    for path in md_files:
        page_id = _page_id_from_path(path, wiki_root)
        relative = path.relative_to(wiki_root).as_posix()
        content = page_contents.get(relative, read_text(path)) if page_contents else read_text(path)
        body = strip_frontmatter(content)
        sources = _frontmatter_sources(content)

        pages[page_id] = {
            "id": page_id,
            "path": path.relative_to(wiki_root.parent).as_posix(),
            "sources": sources,
        }

        for source in sources:
            edges.append({"from": page_id, "to": source, "kind": "supported_by"})

        for link in parse_wikilinks(body):
            resolved = _resolve_target(link, page_id, known)
            if not resolved:
                edges.append({"from": page_id, "to": link.removeprefix("wiki/"), "kind": "references", "broken": True})
                continue
            if resolved not in outlinks_map[page_id]:
                outlinks_map[page_id].append(resolved)
            if page_id not in backlinks_map[resolved]:
                backlinks_map[resolved].append(page_id)
            edges.append({"from": page_id, "to": resolved, "kind": "references"})

        if include_semantic:
            edges.extend(_semantic_edges_for_page(page_id, content, known))

    for page_id in known:
        if page_id in pages:
            pages[page_id]["outlinks"] = outlinks_map.get(page_id, [])
            pages[page_id]["backlinks"] = backlinks_map.get(page_id, [])

    if not include_system_pages:
        pages = {page_id: entry for page_id, entry in pages.items() if not _is_system_page(page_id)}
        edges = [
            edge
            for edge in edges
            if isinstance(edge, dict)
            and not _is_system_page(str(edge.get("from", "")))
            and (
                str(edge.get("to", "")).startswith("raw/")
                or not _is_system_page(str(edge.get("to", "")))
            )
        ]

    return {"pages": pages, "edges": edges}


def graph_delta(before_graph: dict[str, object], after_graph: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    """Compare two graphs and return node/edge/broken-link changes."""
    before_pages = before_graph.get("pages", {})
    after_pages = after_graph.get("pages", {})
    before_edges = [edge for edge in before_graph.get("edges", []) if isinstance(edge, dict)]
    after_edges = [edge for edge in after_graph.get("edges", []) if isinstance(edge, dict)]

    if not isinstance(before_pages, dict):
        before_pages = {}
    if not isinstance(after_pages, dict):
        after_pages = {}

    before_page_ids = set(before_pages)
    after_page_ids = set(after_pages)

    before_edge_map = {_edge_key(edge): edge for edge in before_edges}
    after_edge_map = {_edge_key(edge): edge for edge in after_edges}

    nodes_added = [{"id": page_id, **(after_pages[page_id] if isinstance(after_pages[page_id], dict) else {})} for page_id in sorted(after_page_ids - before_page_ids)]
    nodes_removed = [{"id": page_id, **(before_pages[page_id] if isinstance(before_pages[page_id], dict) else {})} for page_id in sorted(before_page_ids - after_page_ids)]

    nodes_modified: list[dict[str, object]] = []
    for page_id in sorted(before_page_ids & after_page_ids):
        before_entry = before_pages.get(page_id, {})
        after_entry = after_pages.get(page_id, {})
        if not isinstance(before_entry, dict) or not isinstance(after_entry, dict):
            continue
        if before_entry != after_entry:
            nodes_modified.append({"id": page_id, "before": before_entry, "after": after_entry})

    edges_added = [dict(after_edge_map[key]) for key in sorted(after_edge_map) if key not in before_edge_map]
    edges_removed = [dict(before_edge_map[key]) for key in sorted(before_edge_map) if key not in after_edge_map]

    before_known = set(before_pages)
    after_known = set(after_pages)
    broken_before = {_edge_key(edge) for edge in _collect_broken_links(before_edges, before_known)}
    broken_after = {_edge_key(edge) for edge in _collect_broken_links(after_edges, after_known)}

    broken_links_added = [dict(after_edge_map[key]) for key in sorted(broken_after - broken_before) if key in after_edge_map]
    broken_links_resolved = [dict(before_edge_map[key]) for key in sorted(broken_before - broken_after) if key in before_edge_map]

    return {
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "nodes_modified": nodes_modified,
        "edges_added": edges_added,
        "edges_removed": edges_removed,
        "broken_links_added": broken_links_added,
        "broken_links_resolved": broken_links_resolved,
    }


def build_draft_graph(wiki_root: Path, draft_files_dir: Path) -> dict[str, object]:
    """Build semantic graph with draft candidate pages overlaid on the current wiki."""
    page_contents: dict[str, str] = {}
    if draft_files_dir.is_dir():
        for path in sorted(draft_files_dir.rglob("*.md")):
            relative = path.relative_to(draft_files_dir).as_posix()
            page_contents[relative] = read_text(path)
    return build_semantic_graph(wiki_root, page_contents=page_contents)


def page_context(wiki_root: Path, page_id: str) -> PageContext:
    """Return sources, backlinks, and outlinks for a single page."""
    graph = build_navigation_graph(wiki_root)
    pages = graph.get("pages", {})
    if not isinstance(pages, dict) or page_id not in pages:
        return PageContext(page_id=page_id)

    entry = pages[page_id]
    if not isinstance(entry, dict):
        return PageContext(page_id=page_id)

    sources = [str(item) for item in entry.get("sources", [])]
    outlinks = [str(item) for item in entry.get("outlinks", [])]
    backlinks = [str(item) for item in entry.get("backlinks", [])]
    return PageContext(page_id=page_id, sources=sources, backlinks=backlinks, outlinks=outlinks)
