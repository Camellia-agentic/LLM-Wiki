"""Control-plane discovery file and single-instance locking."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from llm_wiki.text import read_text, write_text

CONTROL_SCHEMA_VERSION = 1
API_VERSION = "v1"


def vault_id_for(root: Path) -> str:
    resolved = str(root.resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class ControlState:
    vault_id: str
    token: str
    base_url: str
    api_version: str
    schema_version: int
    updated_at: str
    root: Path

    @property
    def control_path(self) -> Path:
        return self.root / ".llm-wiki" / "control.json"

    @classmethod
    def load_or_create(cls, root: Path, port: int) -> ControlState:
        root = root.resolve()
        runtime = root / ".llm-wiki"
        runtime.mkdir(parents=True, exist_ok=True)
        control_path = runtime / "control.json"
        vault_id = vault_id_for(root)
        base_url = f"http://127.0.0.1:{port}"

        if control_path.exists():
            try:
                raw = json.loads(read_text(control_path))
            except json.JSONDecodeError:
                raw = {}
            if isinstance(raw, dict):
                token = str(raw.get("api_token") or raw.get("token") or "")
                if not token:
                    token = secrets.token_urlsafe(32)
                state = cls(
                    vault_id=str(raw.get("vault_id") or vault_id),
                    token=token,
                    base_url=base_url,
                    api_version=str(raw.get("api_version") or API_VERSION),
                    schema_version=int(raw.get("schema_version") or CONTROL_SCHEMA_VERSION),
                    updated_at=_now_iso(),
                    root=root,
                )
                state.save()
                return state

        state = cls(
            vault_id=vault_id,
            token=secrets.token_urlsafe(32),
            base_url=base_url,
            api_version=API_VERSION,
            schema_version=CONTROL_SCHEMA_VERSION,
            updated_at=_now_iso(),
            root=root,
        )
        state.save()
        return state

    def save(self) -> None:
        self.updated_at = _now_iso()
        payload = {
            "schema_version": self.schema_version,
            "vault_id": self.vault_id,
            "api_token": self.token,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "updated_at": self.updated_at,
        }
        write_text(self.control_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "vault_id": self.vault_id,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "updated_at": self.updated_at,
        }


class InstanceLock:
    """Vault-level lock ensuring only one writer process runs."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.lock_path = self.root / ".llm-wiki" / "instance.lock"
        self._held = False

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                os.kill(pid, 0)
            except OSError:
                return False
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        else:
            return True

    def _read_lock(self) -> tuple[int | None, str]:
        if not self.lock_path.exists():
            return None, ""
        try:
            raw = read_text(self.lock_path).strip().splitlines()
        except OSError:
            return None, ""
        if not raw:
            return None, ""
        try:
            pid = int(raw[0].strip())
        except ValueError:
            return None, ""
        started = raw[1].strip() if len(raw) > 1 else ""
        return pid, started

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        existing_pid, started = self._read_lock()
        if existing_pid is not None and existing_pid != os.getpid() and self._pid_alive(existing_pid):
            raise RuntimeError(
                f"Another LLM Wiki instance is already running for this vault "
                f"(pid={existing_pid}, started={started or 'unknown'})."
            )
        write_text(
            self.lock_path,
            f"{os.getpid()}\n{ _now_iso() }\n",
        )
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        existing_pid, _ = self._read_lock()
        if existing_pid == os.getpid():
            self.lock_path.unlink(missing_ok=True)
        self._held = False

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
