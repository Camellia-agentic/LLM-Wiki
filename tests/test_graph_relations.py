import json
import tempfile
import unittest
from pathlib import Path

from llm_wiki.graph import (
    build_semantic_graph,
    graph_delta,
)
from llm_wiki.relations import (
    merge_relations_into_content,
    parse_page_relations,
    relations_frontmatter_yaml,
    render_relations_section,
    topic_relations_from_analysis,
)
from llm_wiki.text import write_text


def _sample_concept_page() -> str:
    relations = [
        {
            "predicate": "uses",
            "target": "concepts/erasure-code",
            "source": "raw/sources/minio-demo.md",
            "evidence_quote": "MinIO uses erasure coding for durability.",
            "evidence_anchor": "L42-L44",
            "confidence": "medium",
            "verification": "source_backed",
        }
    ]
    yaml_block = relations_frontmatter_yaml(relations)
    section = render_relations_section(relations)
    return (
        "---\n"
        'title: "MinIO"\n'
        "type: entity\n"
        "sources:\n"
        '  - "raw/sources/minio-demo.md"\n'
        "updated: 2026-08-03\n"
        f"{yaml_block}\n"
        "---\n\n"
        "# MinIO\n\n"
        "## 实体说明\n\n"
        "对象存储系统。\n\n"
        f"{section}"
    )


class GraphRelationsTests(unittest.TestCase):
    def test_relations_frontmatter_roundtrip(self) -> None:
        relations = [
            {
                "predicate": "uses",
                "target": "concepts/erasure-code",
                "source": "raw/sources/minio-demo.md",
                "evidence_quote": "逐字引句",
                "evidence_anchor": "L120-L123",
            }
        ]
        yaml_block = relations_frontmatter_yaml(relations)
        self.assertIn("predicate: uses", yaml_block)
        self.assertIn("evidence_quote:", yaml_block)
        content = merge_relations_into_content("# Title\n\nBody.\n", relations)
        parsed = parse_page_relations(content)
        self.assertEqual(1, len(parsed))
        self.assertEqual("uses", parsed[0]["predicate"])
        self.assertEqual("concepts/erasure-code", parsed[0]["target"])

    def test_render_relations_section_contains_wikilinks(self) -> None:
        section = render_relations_section(
            [
                {
                    "predicate": "uses",
                    "target": "concepts/erasure-code",
                    "source": "raw/sources/minio-demo.md",
                    "evidence_anchor": "L120",
                }
            ]
        )
        self.assertIn("## 关系", section)
        self.assertIn("[[wiki/concepts/erasure-code]]", section)
        self.assertIn("[[raw/sources/minio-demo.md#L120]]", section)

    def test_semantic_graph_includes_predicate_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wiki_root = Path(directory) / "wiki"
            concepts = wiki_root / "concepts"
            entities = wiki_root / "entities"
            concepts.mkdir(parents=True)
            entities.mkdir(parents=True)
            write_text(wiki_root / "concepts" / "erasure-code.md", "# 纠删码\n\n概念页。\n")
            write_text(wiki_root / "entities" / "minio.md", _sample_concept_page())

            graph = build_semantic_graph(wiki_root)
            edges = graph.get("edges", [])
            semantic = [
                edge
                for edge in edges
                if isinstance(edge, dict)
                and edge.get("from") == "entities/minio"
                and edge.get("kind") == "uses"
            ]
            self.assertEqual(1, len(semantic))
            self.assertEqual("concepts/erasure-code", semantic[0]["to"])
            self.assertEqual("MinIO uses erasure coding for durability.", semantic[0]["evidence_quote"])

    def test_semantic_graph_skips_system_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wiki_root = Path(directory) / "wiki"
            (wiki_root / "concepts").mkdir(parents=True)
            write_text(wiki_root / "concepts" / "demo.md", "# Demo\n")
            write_text(
                wiki_root / "index.md",
                "---\ntitle: index\ntype: index\nsources: []\nupdated: 2026-08-03\n---\n\n# Index\n\n[[concepts/demo]]\n",
            )

            graph = build_semantic_graph(wiki_root)
            self.assertNotIn("index", graph["pages"])

    def test_graph_delta_reports_added_semantic_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wiki_root = Path(directory) / "wiki"
            concepts = wiki_root / "concepts"
            entities = wiki_root / "entities"
            concepts.mkdir(parents=True)
            entities.mkdir(parents=True)
            write_text(wiki_root / "concepts" / "erasure-code.md", "# 纠删码\n\n概念页。\n")
            write_text(wiki_root / "entities" / "minio.md", "# MinIO\n\n无关系。\n")

            before = build_semantic_graph(wiki_root)
            write_text(wiki_root / "entities" / "minio.md", _sample_concept_page())
            after = build_semantic_graph(wiki_root)
            delta = graph_delta(before, after)

            added_kinds = {edge.get("kind") for edge in delta["edges_added"] if isinstance(edge, dict)}
            self.assertIn("uses", added_kinds)
            self.assertTrue(any(item.get("id") == "entities/minio" for item in delta["nodes_modified"]))

    def test_topic_relations_from_analysis(self) -> None:
        analysis_relations = [
            {
                "subject": "MinIO",
                "predicate": "uses",
                "object": "纠删码",
                "evidence_quote": "quote",
                "evidence_anchor": "L10",
            }
        ]
        page_relations = topic_relations_from_analysis(
            analysis_relations,
            subject="MinIO",
            source_path="raw/sources/minio-demo.md",
            planned_paths={"concepts/纠删码"},
        )
        self.assertEqual(1, len(page_relations))
        self.assertEqual("uses", page_relations[0]["predicate"])
        self.assertEqual("concepts/纠删码", page_relations[0]["target"])

    def test_relations_section_backup_parsing(self) -> None:
        content = (
            "# Page\n\n"
            "## 关系\n\n"
            "- `part_of` [[wiki/concepts/storage]]（[[raw/sources/demo.md#L5]]）\n"
        )
        parsed = parse_page_relations(content)
        self.assertEqual(1, len(parsed))
        self.assertEqual("part_of", parsed[0]["predicate"])
        self.assertEqual("concepts/storage", parsed[0]["target"])
        self.assertEqual("raw/sources/demo.md", parsed[0]["source"])


if __name__ == "__main__":
    unittest.main()
