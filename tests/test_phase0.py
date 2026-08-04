import json
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path

from llm_wiki.chunking import chunk_document
from llm_wiki.control import ControlState, vault_id_for
from llm_wiki.pipeline import merge_chunk_analyses
from llm_wiki.repository import Repository, migrate_state
from llm_wiki.text import PAGE_TYPES


SAMPLE = "# Title\n\n" + ("段落内容。\n\n" * 2000) + "\n## Late Section\n\n关键证据在第 14000 字符之后。\n"


class ChunkingTests(unittest.TestCase):
    def test_late_evidence_in_last_chunk(self) -> None:
        chunks = chunk_document(SAMPLE, target_size=8000)
        self.assertGreater(len(chunks), 1)
        joined = "\n".join(c.content for c in chunks)
        self.assertIn("关键证据在第 14000 字符之后", joined)
        last = chunks[-1]
        self.assertIn("Late Section", last.heading_path)
        self.assertGreaterEqual(last.end_line, last.start_line)

    def test_code_fence_not_split(self) -> None:
        doc = "# Doc\n\n```python\nprint('x')\nprint('y')\n```\n"
        chunks = chunk_document(doc, target_size=20)
        for chunk in chunks:
            if "```" in chunk.content:
                self.assertEqual(chunk.content.count("```"), 2)


class PipelineMergeTests(unittest.TestCase):
    def test_merge_dedupes_concepts(self) -> None:
        a = {"concepts": [{"name": "RDMA", "summary": "a", "chunk_id": "chunk_0001"}], "relations": [], "review_items": []}
        b = {"concepts": [{"name": "RDMA", "summary": "b", "chunk_id": "chunk_0002"}], "relations": [], "review_items": []}
        merged = merge_chunk_analyses([a, b])
        self.assertEqual(1, len(merged["concepts"]))


class RepositoryTests(unittest.TestCase):
    def test_migrate_legacy_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            runtime = root / ".llm-wiki"
            runtime.mkdir(parents=True)
            legacy = {"sources": {"abc": {"title": "T", "raw_path": "raw/sources/t.md", "digest": "abc"}}}
            (runtime / "state.json").write_text(json.dumps(legacy), encoding="utf-8")
            repo = Repository(root)
            state = repo.load_state()
            self.assertGreaterEqual(state["schema_version"], 2)
            self.assertEqual(1, len(state["acquisitions"]))
            self.assertEqual(1, len(state["snapshots"]))


class ControlAuthTests(unittest.TestCase):
    def test_vault_id_stable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "vault"
            root.mkdir()
            self.assertEqual(vault_id_for(root), vault_id_for(root))

    def test_control_persists_token(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "vault"
            root.mkdir()
            first = ControlState.load_or_create(root, 8765)
            second = ControlState.load_or_create(root, 8765)
            self.assertEqual(first.token, second.token)


class EntityTypeTests(unittest.TestCase):
    def test_page_types_mapping(self) -> None:
        self.assertEqual("entity", PAGE_TYPES["entities"])
        self.assertEqual("concept", PAGE_TYPES["concepts"])


if __name__ == "__main__":
    unittest.main()
