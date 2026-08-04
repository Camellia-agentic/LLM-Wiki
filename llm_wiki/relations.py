"""Relation frontmatter and ## 关系 section rendering."""

from __future__ import annotations

import json
import re
from typing import Callable

from llm_wiki.text import slug, strip_frontmatter, yaml_quote

SEMANTIC_PREDICATES = frozenset(
    {
        "related_to",
        "part_of",
        "contains",
        "uses",
        "implements",
        "depends_on",
        "contrasts_with",
        "derived_from",
        "supports",
        "contradicts",
    }
)

RELATIONS_SECTION_RE = re.compile(r"(?ms)^## 关系\s*$.*?(?=^## |\Z)")
RELATION_LINE_RE = re.compile(
    r"^-\s+`([^`]+)`\s+\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]"
    r"(?:\s*[（(]\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\][）)])?\s*$"
)
FRONTMATTER_RELATIONS_RE = re.compile(
    r"^relations:\n((?:  - .+\n(?:    .+\n)*)*)",
    re.MULTILINE,
)
RELATION_ITEM_RE = re.compile(
    r"^  - predicate:\s*(.+)\n"
    r"(?:    target:\s*(.+)\n)?"
    r"(?:    source:\s*(.+)\n)?"
    r"(?:    evidence_quote:\s*(.+)\n)?"
    r"(?:    evidence_anchor:\s*(.+)\n)?"
    r"(?:    confidence:\s*(.+)\n)?"
    r"(?:    verification:\s*(.+)\n)?",
    re.MULTILINE,
)


def normalise_predicate(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_")
    return cleaned if cleaned in SEMANTIC_PREDICATES else "related_to"


def _parse_yaml_scalar(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw.strip("\"'")
    return str(parsed).strip()


def _relation_key(relation: dict) -> tuple[str, ...]:
    return (
        str(relation.get("predicate", "")).strip(),
        str(relation.get("target", "")).strip(),
        str(relation.get("source", "")).strip(),
        str(relation.get("evidence_quote", "")).strip(),
    )


def merge_relations(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged: list[dict] = [dict(item) for item in existing if isinstance(item, dict)]
    seen = {_relation_key(item) for item in merged}
    for relation in incoming:
        if not isinstance(relation, dict):
            continue
        key = _relation_key(relation)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(relation))
    return merged


def analysis_relation_to_page(
    relation: dict,
    *,
    subject: str,
    source_path: str,
    target: str,
) -> dict | None:
    predicate = normalise_predicate(str(relation.get("predicate", "related_to")))
    evidence_quote = str(relation.get("evidence_quote", "")).strip()
    evidence_anchor = str(relation.get("evidence_anchor", "")).strip()
    if not target:
        return None
    page_relation = {
        "predicate": predicate,
        "target": target.removeprefix("wiki/"),
        "source": source_path,
    }
    if evidence_quote:
        page_relation["evidence_quote"] = evidence_quote
    if evidence_anchor:
        page_relation["evidence_anchor"] = evidence_anchor
    confidence = str(relation.get("confidence", "")).strip()
    if confidence:
        page_relation["confidence"] = confidence
    verification = str(relation.get("verification", "")).strip() or ("source_backed" if evidence_quote else "")
    if verification:
        page_relation["verification"] = verification
    if str(relation.get("subject", "")).strip() and str(relation.get("subject", "")).strip() != subject:
        return None
    return page_relation


def relations_frontmatter_yaml(relations: list[dict]) -> str:
    if not relations:
        return ""
    lines = ["relations:"]
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        predicate = normalise_predicate(str(relation.get("predicate", "related_to")))
        target = str(relation.get("target", "")).strip().removeprefix("wiki/")
        source = str(relation.get("source", "")).strip()
        if not target:
            continue
        lines.append(f"  - predicate: {predicate}")
        lines.append(f"    target: {yaml_quote(f'wiki/{target}')}")
        if source:
            lines.append(f"    source: {yaml_quote(source)}")
        evidence_quote = str(relation.get("evidence_quote", "")).strip()
        if evidence_quote:
            lines.append(f"    evidence_quote: {yaml_quote(evidence_quote)}")
        evidence_anchor = str(relation.get("evidence_anchor", "")).strip()
        if evidence_anchor:
            lines.append(f"    evidence_anchor: {yaml_quote(evidence_anchor)}")
        confidence = str(relation.get("confidence", "")).strip()
        if confidence:
            lines.append(f"    confidence: {yaml_quote(confidence)}")
        verification = str(relation.get("verification", "")).strip()
        if verification:
            lines.append(f"    verification: {yaml_quote(verification)}")
    return "\n".join(lines)


def _evidence_link(source: str, evidence_anchor: str) -> str:
    anchor = evidence_anchor.strip()
    if not anchor:
        return source
    line_match = re.search(r"L(\d+)", anchor, re.IGNORECASE)
    if line_match:
        return f"{source}#L{line_match.group(1)}"
    cn_match = re.search(r"第?\s*(\d+)", anchor)
    if cn_match:
        return f"{source}#L{cn_match.group(1)}"
    return source


def render_relations_section(relations: list[dict]) -> str:
    if not relations:
        return ""
    lines = ["## 关系", ""]
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        predicate = normalise_predicate(str(relation.get("predicate", "related_to")))
        target = str(relation.get("target", "")).strip().removeprefix("wiki/")
        if not target:
            continue
        source = str(relation.get("source", "")).strip()
        evidence_anchor = str(relation.get("evidence_anchor", "")).strip()
        line = f"- `{predicate}` [[wiki/{target}]]"
        if source:
            line += f"（[[{_evidence_link(source, evidence_anchor)}]]）"
        lines.append(line)
    if len(lines) <= 2:
        return ""
    return "\n".join(lines) + "\n"


def parse_relations_frontmatter(content: str) -> list[dict]:
    header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
    if not header:
        return []
    block = FRONTMATTER_RELATIONS_RE.search(header.group(1))
    if not block:
        return []
    relations: list[dict] = []
    for match in RELATION_ITEM_RE.finditer(block.group(1)):
        relation = {
            "predicate": normalise_predicate(_parse_yaml_scalar(match.group(1))),
            "target": _parse_yaml_scalar(match.group(2) or "").removeprefix("wiki/"),
        }
        source = _parse_yaml_scalar(match.group(3) or "")
        if source:
            relation["source"] = source
        evidence_quote = _parse_yaml_scalar(match.group(4) or "")
        if evidence_quote:
            relation["evidence_quote"] = evidence_quote
        evidence_anchor = _parse_yaml_scalar(match.group(5) or "")
        if evidence_anchor:
            relation["evidence_anchor"] = evidence_anchor
        confidence = _parse_yaml_scalar(match.group(6) or "")
        if confidence:
            relation["confidence"] = confidence
        verification = _parse_yaml_scalar(match.group(7) or "")
        if verification:
            relation["verification"] = verification
        if relation.get("target"):
            relations.append(relation)
    return relations


def parse_relations_section(content: str) -> list[dict]:
    body = strip_frontmatter(content)
    section = RELATIONS_SECTION_RE.search(body)
    if not section:
        return []
    relations: list[dict] = []
    for line in section.group(0).splitlines()[1:]:
        match = RELATION_LINE_RE.match(line.strip())
        if not match:
            continue
        source = match.group(3).strip() if match.group(3) else ""
        evidence_anchor = ""
        if "#L" in source:
            anchor_match = re.search(r"#L(\d+)", source)
            if anchor_match:
                evidence_anchor = f"L{anchor_match.group(1)}"
            source = source.split("#", 1)[0]
        relation = {
            "predicate": normalise_predicate(match.group(1)),
            "target": match.group(2).strip().removeprefix("wiki/").removesuffix(".md"),
        }
        if source:
            relation["source"] = source
        if evidence_anchor:
            relation["evidence_anchor"] = evidence_anchor
        relations.append(relation)
    return relations


def parse_page_relations(content: str) -> list[dict]:
    frontmatter_relations = parse_relations_frontmatter(content)
    if frontmatter_relations:
        return frontmatter_relations
    return parse_relations_section(content)


def merge_relations_into_content(content: str, incoming: list[dict]) -> str:
    if not incoming:
        return content
    existing = parse_page_relations(content)
    merged = merge_relations(existing, incoming)
    if not merged:
        return content

    yaml_block = relations_frontmatter_yaml(merged)
    section_block = render_relations_section(merged)

    header = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
    if header:
        fm_body = header.group(1)
        fm_body = FRONTMATTER_RELATIONS_RE.sub("", fm_body).rstrip()
        if fm_body:
            fm_body = fm_body + "\n" + yaml_block
        else:
            fm_body = yaml_block
        content = "---\n" + fm_body + "\n---\n" + content[header.end() :]
    else:
        content = "---\n" + yaml_block + "\n---\n" + content

    body = strip_frontmatter(content)
    body = RELATIONS_SECTION_RE.sub("", body).rstrip()
    if section_block:
        content = re.sub(r"\A---\n.*?\n---\n", lambda match: match.group(0), content, count=1, flags=re.DOTALL)
        header = re.match(r"\A---\n.*?\n---\n", content, re.DOTALL)
        prefix = header.group(0) if header else ""
        body_part = content[len(prefix) :] if prefix else content
        body_part = body_part.rstrip() + "\n\n" + section_block
        content = prefix + body_part
    return content.rstrip() + "\n"


def resolve_relation_target(
    object_name: str,
    *,
    planned_paths: set[str] | None = None,
    wiki_exists: Callable[[str], bool] | None = None,
) -> str:
    cleaned = object_name.strip().removeprefix("wiki/").removesuffix(".md")
    if cleaned.startswith(("concepts/", "entities/", "sources/")):
        return cleaned
    for kind in ("concepts", "entities"):
        candidate = f"{kind}/{slug(cleaned)}"
        if planned_paths and candidate in planned_paths:
            return candidate
        if wiki_exists and wiki_exists(candidate):
            return candidate
    return f"concepts/{slug(cleaned, 'topic')}"


def topic_relations_from_analysis(
    analysis_relations: list[dict],
    *,
    subject: str,
    source_path: str,
    planned_paths: set[str] | None = None,
    wiki_exists: Callable[[str], bool] | None = None,
) -> list[dict]:
    page_relations: list[dict] = []
    for relation in analysis_relations:
        if not isinstance(relation, dict):
            continue
        rel_subject = str(relation.get("subject", subject)).strip()
        if rel_subject.casefold() != subject.casefold():
            continue
        target_name = str(relation.get("object", relation.get("target", ""))).strip()
        if not target_name:
            continue
        target = resolve_relation_target(
            target_name,
            planned_paths=planned_paths,
            wiki_exists=wiki_exists,
        )
        page_relation = analysis_relation_to_page(
            relation,
            subject=subject,
            source_path=source_path,
            target=f"wiki/{target}",
        )
        if page_relation:
            page_relations.append(page_relation)
    return page_relations
