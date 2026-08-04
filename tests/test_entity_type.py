import tempfile
import unittest
from pathlib import Path

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "wiki.py"
SPEC = importlib.util.spec_from_file_location("wiki_tool", SCRIPT)
assert SPEC and SPEC.loader
wiki_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_tool)


class EntityTypeTests(unittest.TestCase):
    def test_new_entity_page_uses_entity_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            path, content, _ = wiki.render_topic_page(
                "entities",
                {"name": "MinIO", "summary": "对象存储。"},
                "raw/sources/minio.md",
                "MinIO 资料",
            )
            self.assertIsNotNone(path)
            self.assertIn("type: entity", content)
            self.assertNotIn("type: entitie", content)


if __name__ == "__main__":
    unittest.main()
