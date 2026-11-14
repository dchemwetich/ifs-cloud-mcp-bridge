"""Saved sessions: ~/.ifs-mcp/session.json plus an in-memory token store.

Session records keep the TypeScript layout (camelCase keys, epoch milliseconds) so
both servers can read the same file.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .. import config

# session key (environment name) -> {accessToken, refreshToken?, expiresAt, issuedAt?, userId}
token_store: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _session_file():
    return config.config_dir() / "session.json"


def load_sessions() -> dict[str, dict[str, Any]]:
    f = _session_file()
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    return {}


def _write(sessions: dict[str, Any]) -> None:
    config.ensure_dir()
    f = _session_file()
    f.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def set_token(key: str, data: dict[str, Any]) -> None:
    with _lock:
        token_store[key] = _clean(data)


def get_token(key: str) -> dict[str, Any] | None:
    with _lock:
        return token_store.get(key)


def save_session(key: str, data: dict[str, Any]) -> None:
    try:
        with _lock:
            sessions = load_sessions()
            sessions[key] = _clean(data)
            _write(sessions)
    except OSError:
        pass


def remove_session(key: str) -> None:
    try:
        with _lock:
            sessions = load_sessions()
            if sessions.pop(key, None) is not None:
                _write(sessions)
    except OSError:
        pass
    with _lock:
        token_store.pop(key, None)


def get_current_session_id() -> str | None:
    return config.get_active_session_key()


def initialize_token_store() -> None:
    for key, data in load_sessions().items():
        if isinstance(data, dict):
            set_token(key, data)
