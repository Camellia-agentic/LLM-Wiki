import unittest

from llm_wiki.text import compact, slug


class TextUtilTests(unittest.TestCase):
    def test_slug_preserves_cjk(self) -> None:
        self.assertEqual(slug("纠删码 Erasure Code"), "纠删码-erasure-code")

    def test_compact_truncates_with_ellipsis(self) -> None:
        self.assertTrue(compact("a" * 400, 50).endswith("…"))


if __name__ == "__main__":
    unittest.main()
