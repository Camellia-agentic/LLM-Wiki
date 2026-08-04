"""Chunked LLM analysis and merge helpers."""

from __future__ import annotations

from typing import Any, Callable

from llm_wiki.chunking import chunk_document


def _normalise_name(value: str) -> str:
    return value.strip().casefold()


def _merge_text(existing: str, incoming: str) -> str:
    existing = existing.strip()
    incoming = incoming.strip()
    if not existing:
        return incoming
    if not incoming or incoming in existing:
        return existing
    if existing in incoming:
        return incoming
    return f"{existing} {incoming}"


def _dedupe_key(item: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(item.get(field, "")).strip() for field in fields)


def _attach_chunk_id(item: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    merged = dict(item)
    merged.setdefault("chunk_id", chunk_id)
    return merged


def merge_chunk_analyses(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-chunk analyses without inventing facts absent from inputs."""
    merged: dict[str, Any] = {
        "summary": "",
        "claims": [],
        "concepts": [],
        "entities": [],
        "relations": [],
        "links": [],
        "review_items": [],
    }
    concept_index: dict[str, int] = {}
    entity_index: dict[str, int] = {}
    relation_seen: set[tuple[str, ...]] = set()
    review_seen: set[tuple[str, ...]] = set()
    claim_seen: set[str] = set()
    link_seen: set[str] = set()
    summaries: list[str] = []

    for analysis in analyses:
        if not isinstance(analysis, dict) or not analysis:
            continue

        summary = str(analysis.get("summary", "")).strip()
        if summary:
            summaries.append(summary)

        for claim in analysis.get("claims", []):
            text = str(claim).strip()
            if text and text not in claim_seen:
                claim_seen.add(text)
                merged["claims"].append(text)

        for link in analysis.get("links", []):
            text = str(link).strip()
            if text and text not in link_seen:
                link_seen.add(text)
                merged["links"].append(text)

        for concept in analysis.get("concepts", []):
            if not isinstance(concept, dict):
                continue
            name = str(concept.get("name", "")).strip()
            if not name:
                continue
            key = _normalise_name(name)
            if key in concept_index:
                existing = merged["concepts"][concept_index[key]]
                existing["summary"] = _merge_text(str(existing.get("summary", "")), str(concept.get("summary", "")))
                if concept.get("chunk_id") and not existing.get("chunk_id"):
                    existing["chunk_id"] = concept["chunk_id"]
            else:
                concept_index[key] = len(merged["concepts"])
                merged["concepts"].append(dict(concept))

        for entity in analysis.get("entities", []):
            if not isinstance(entity, dict):
                continue
            name = str(entity.get("name", "")).strip()
            if not name:
                continue
            key = _normalise_name(name)
            if key in entity_index:
                existing = merged["entities"][entity_index[key]]
                existing["summary"] = _merge_text(str(existing.get("summary", "")), str(entity.get("summary", "")))
                if entity.get("chunk_id") and not existing.get("chunk_id"):
                    existing["chunk_id"] = entity["chunk_id"]
            else:
                entity_index[key] = len(merged["entities"])
                merged["entities"].append(dict(entity))

        for relation in analysis.get("relations", []):
            if not isinstance(relation, dict):
                continue
            key = _dedupe_key(
                relation,
                ("subject", "predicate", "object", "evidence_quote"),
            )
            if key in relation_seen:
                continue
            relation_seen.add(key)
            merged["relations"].append(dict(relation))

        for item in analysis.get("review_items", []):
            if not isinstance(item, dict):
                continue
            key = _dedupe_key(item, ("kind", "text", "evidence_quote", "evidence_anchor"))
            if key in review_seen:
                continue
            review_seen.add(key)
            merged["review_items"].append(dict(item))

    if summaries:
        merged["summary"] = summaries[0]
        if len(summaries) > 1:
            merged["summary"] = _merge_text(summaries[0], " ".join(summaries[1:3]))

    return merged


def analyze_content_in_chunks(
    wiki: Any,
    title: str,
    raw_path: str,
    content: str,
    args: Any,
    llm_json_fn: Callable[[str, str, Any, str], dict[str, Any]],
) -> dict[str, Any]:
    """Chunk *content*, run stage-1 analysis per chunk, and merge results."""
    from llm_wiki.text import read_text

    if not getattr(args, "llm_url", None) or not getattr(args, "model", None):
        return {}

    index_path = wiki.wiki / "index.md"
    purpose_path = wiki.root / "purpose.md"
    index = read_text(index_path) if index_path.exists() else ""
    purpose = read_text(purpose_path) if purpose_path.exists() else ""

    system = (
        "You are stage 1 of a Chinese knowledge-wiki ingest pipeline. Return only a JSON object. "
        "Extract evidence-backed facts, concepts, entities, contradictions, and gaps. Never invent facts. "
        "Schema: {summary:string, claims:[string], concepts:[{name:string,summary:string}], "
        "entities:[{name:string,summary:string}], relations:[{subject:string,predicate:string,object:string,"
        "evidence_quote:string,evidence_anchor:string}], links:[string], "
        "review_items:[{kind:'source_claim'|'gap'|'research_question',text:string,evidence_quote:string,"
        "evidence_anchor:string,confidence:string}]}. "
        "A source_claim is a concrete claim in the supplied source that needs human verification. It MUST include an exact, contiguous "
        "verbatim evidence_quote copied from the source text; never paraphrase it and never create a source_claim without it. "
        "Use gap for missing material and research_question for questions needing external or cross-source research; both must have empty "
        "evidence_quote and evidence_anchor. Do not turn requests for more information into source_claims."
    )

    chunks = chunk_document(content)
    if not chunks:
        return {}

    analyses: list[dict[str, Any]] = []
    for chunk in chunks:
        heading = " > ".join(chunk.heading_path) if chunk.heading_path else "(root)"
        user = (
            f"Purpose:\n{purpose[:3000]}\n\nCurrent index:\n{index[:5000]}\n\n"
            f"Immutable source: {raw_path}\nTitle: {title}\n"
            f"Chunk: {chunk.id}\nHeading path: {heading}\nLines: {chunk.start_line}-{chunk.end_line}\n\n"
            f"Source text:\n{chunk.content}"
        )
        result = llm_json_fn(system, user, args, f"第一阶段分析 {chunk.id}")
        if not result:
            continue

        enriched = dict(result)
        for concept in enriched.get("concepts", []):
            if isinstance(concept, dict):
                concept.setdefault("chunk_id", chunk.id)
        for entity in enriched.get("entities", []):
            if isinstance(entity, dict):
                entity.setdefault("chunk_id", chunk.id)
        for relation in enriched.get("relations", []):
            if isinstance(relation, dict):
                relation.setdefault("chunk_id", chunk.id)
        for item in enriched.get("review_items", []):
            if isinstance(item, dict):
                item.setdefault("chunk_id", chunk.id)
        analyses.append(enriched)

    return merge_chunk_analyses(analyses)
