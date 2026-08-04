import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from llm_wiki.config import apply_config_to_args, load_config, parse_toml


class ConfigTests(unittest.TestCase):
    def test_parse_toml_sections(self) -> None:
        text = """
[llm]
active = "deepseek"

[llm.profiles.deepseek]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
"""
        tables = parse_toml(text)
        self.assertEqual("deepseek", tables["llm"]["active"])
        self.assertEqual("deepseek-chat", tables["llm.profiles.deepseek"]["model"])

    def test_apply_config_fills_args(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.toml").write_text(
                """
[llm]
active = "deepseek"

[llm.profiles.deepseek]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
""",
                encoding="utf-8",
            )
            os.environ["DEEPSEEK_API_KEY"] = "test-key"
            try:
                args = Namespace(llm_url=None, model=None, api_key="", timeout=120, max_tokens=1800)
                cfg = apply_config_to_args(args, root)
                self.assertEqual("deepseek-chat", args.model)
                self.assertTrue(args.llm_url.endswith("/chat/completions"))
                self.assertEqual("test-key", args.api_key)
                self.assertTrue(cfg.model_ready())
            finally:
                os.environ.pop("DEEPSEEK_API_KEY", None)

    def test_cli_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.toml").write_text("[llm]\nactive = \"openai\"\n", encoding="utf-8")
            args = Namespace(
                llm_url="http://override.test/v1/chat/completions",
                model="override-model",
                api_key="k",
                timeout=120,
                max_tokens=1800,
            )
            apply_config_to_args(args, root)
            self.assertEqual("override-model", args.model)
            self.assertIn("override.test", args.llm_url)


if __name__ == "__main__":
    unittest.main()
