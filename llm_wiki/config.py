"""Load LLM API settings from config.toml (stdlib-only subset parser)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_wiki.text import read_text

CONFIG_FILENAME = "config.toml"
EXAMPLE_FILENAME = "config.toml.example"

_BUILTIN_PROFILES: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "ollama": {
        "label": "Ollama 本地",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3:8b",
        "api_key_env": "LLM_WIKI_API_KEY",
    },
}


@dataclass
class LlmProfile:
    name: str
    label: str
    base_url: str
    model: str
    api_key_env: str = "LLM_WIKI_API_KEY"

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def resolve_api_key(self) -> str:
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        return os.environ.get("LLM_WIKI_API_KEY", "")

    def public_dict(self) -> dict[str, Any]:
        host = ""
        try:
            from urllib.parse import urlparse

            host = urlparse(self.base_url).netloc
        except Exception:
            host = self.base_url
        return {
            "profile": self.name,
            "label": self.label,
            "model": self.model,
            "endpoint_host": host,
            "api_key_set": bool(self.resolve_api_key()),
        }


@dataclass
class WikiConfig:
    path: Path | None
    active_profile: str = ""
    profiles: dict[str, LlmProfile] = field(default_factory=dict)
    timeout: int = 120
    max_tokens: int = 1800

    @property
    def active(self) -> LlmProfile | None:
        if not self.active_profile:
            return None
        return self.profiles.get(self.active_profile)

    def model_ready(self) -> bool:
        profile = self.active
        return bool(profile and profile.model and profile.chat_completions_url)

    def public_dict(self) -> dict[str, Any]:
        profile = self.active
        return {
            "source": str(self.path) if self.path else "",
            "configured": profile is not None,
            "model_ready": self.model_ready() and bool(profile and profile.resolve_api_key()),
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "profiles": [name for name in self.profiles],
            "active": profile.public_dict() if profile else None,
        }


def _strip_comment(line: str) -> str:
    in_string = False
    quote = ""
    for index, char in enumerate(line):
        if char in "\"'" and (index == 0 or line[index - 1] != "\\"):
            if not in_string:
                in_string = True
                quote = char
            elif quote == char:
                in_string = False
        if char == "#" and not in_string:
            return line[:index].strip()
    return line.strip()


def _parse_value(raw: str) -> str | int | float | bool:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw in {"true", "false"}:
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def parse_toml(text: str) -> dict[str, dict[str, Any]]:
    tables: dict[str, dict[str, Any]] = {}
    current = ""
    for line in text.splitlines():
        line = _strip_comment(line)
        if not line:
            continue
        section = re.match(r"^\[([^\]]+)\]$", line)
        if section:
            current = section.group(1).strip()
            tables.setdefault(current, {})
            continue
        pair = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$", line)
        if pair and current:
            tables[current][pair.group(1)] = _parse_value(pair.group(2))
    return tables


def config_path(root: Path) -> Path:
    return root.resolve() / CONFIG_FILENAME


def load_config(root: Path) -> WikiConfig:
    path = config_path(root)
    cfg = WikiConfig(path=None)
    if not path.is_file():
        return cfg

    tables = parse_toml(read_text(path))
    cfg.path = path

    llm_root = tables.get("llm", {})
    active = str(llm_root.get("active", "")).strip()

    profiles: dict[str, LlmProfile] = {}
    for name, defaults in _BUILTIN_PROFILES.items():
        section = tables.get(f"llm.profiles.{name}", {})
        merged = {**defaults, **{k: str(v) for k, v in section.items() if v is not None}}
        profiles[name] = LlmProfile(
            name=name,
            label=merged.get("label", name),
            base_url=merged["base_url"],
            model=merged["model"],
            api_key_env=str(merged.get("api_key_env", "LLM_WIKI_API_KEY")),
        )

    for section_name, values in tables.items():
        if not section_name.startswith("llm.profiles."):
            continue
        name = section_name.removeprefix("llm.profiles.")
        if name in profiles:
            continue
        profiles[name] = LlmProfile(
            name=name,
            label=str(values.get("label", name)),
            base_url=str(values.get("base_url", "")),
            model=str(values.get("model", "")),
            api_key_env=str(values.get("api_key_env", "LLM_WIKI_API_KEY")),
        )

    custom = tables.get("llm.custom", {})
    if custom:
        profiles["custom"] = LlmProfile(
            name="custom",
            label=str(custom.get("label", "自定义")),
            base_url=str(custom.get("base_url", "")),
            model=str(custom.get("model", "")),
            api_key_env=str(custom.get("api_key_env", "LLM_WIKI_API_KEY")),
        )

    server = tables.get("server", {})
    cfg.timeout = int(server.get("timeout", cfg.timeout))
    cfg.max_tokens = int(server.get("max_tokens", cfg.max_tokens))
    cfg.active_profile = active or str(llm_root.get("provider", "")).strip()
    cfg.profiles = profiles
    return cfg


def apply_config_to_args(args: Any, root: Path) -> WikiConfig:
    """Fill missing CLI LLM fields from config.toml. CLI flags take precedence."""
    cfg = load_config(root)
    profile = cfg.active
    if profile:
        if not getattr(args, "llm_url", None):
            args.llm_url = profile.chat_completions_url
        if not getattr(args, "model", None):
            args.model = profile.model
        if not getattr(args, "api_key", None):
            args.api_key = profile.resolve_api_key()
    if getattr(args, "timeout", None) in {None, 120} and cfg.timeout != 120:
        args.timeout = cfg.timeout
    if getattr(args, "max_tokens", None) in {None, 1800} and cfg.max_tokens != 1800:
        args.max_tokens = cfg.max_tokens
    args.wiki_config = cfg
    return cfg
