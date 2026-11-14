"""Multi-environment configuration for IFS Cloud instances.

Stored in ~/.ifs-mcp/config.json so it persists across updates. Client secrets are
never returned by anything here except get_client_secret(), which only the
client_credentials token request may call (enforced by a test).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal

AuthMode = Literal["authorization_code", "client_credentials"]
SecretSource = Literal["env", "config", "missing"]


def config_dir() -> Path:
    return Path.home() / ".ifs-mcp"


def config_file() -> Path:
    return config_dir() / "config.json"


def ensure_dir() -> None:
    d = config_dir()
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def _read_stored() -> dict[str, Any]:
    """config.json as stored, including any hand-edited clientSecret."""
    try:
        f = config_file()
        if f.exists():
            raw = json.loads(f.read_text(encoding="utf-8"))
            return {
                "activeEnv": raw.get("activeEnv"),
                "environments": raw.get("environments") or {},
            }
    except (OSError, ValueError, AttributeError):
        pass
    return {"activeEnv": None, "environments": {}}


def _write_stored(stored: dict[str, Any]) -> None:
    ensure_dir()
    f = config_file()
    f.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def _without_secrets(stored: dict[str, Any]) -> dict[str, Any]:
    envs = {name: {k: v for k, v in env.items() if k != "clientSecret"} for name, env in stored["environments"].items()}
    return {"activeEnv": stored["activeEnv"], "environments": envs}


def auth_mode_of(env: dict[str, Any] | None) -> AuthMode:
    return "client_credentials" if env and env.get("authMode") == "client_credentials" else "authorization_code"


def load_config() -> dict[str, Any]:
    """Config as seen by every tool: environments only, never a client secret."""
    return _without_secrets(_read_stored())


def list_environments() -> dict[str, Any]:
    return load_config()


def get_active_env_name() -> str | None:
    return load_config()["activeEnv"]


def get_active_session_key() -> str | None:
    """Active environment name, or "default" in legacy env-var mode, else None."""
    cfg = load_config()
    if cfg["activeEnv"]:
        return cfg["activeEnv"]
    if os.environ.get("API_BASE_URL"):
        return "default"
    return None


def get_environment(name: str | None = None) -> dict[str, Any] | None:
    cfg = load_config()
    key = name if name is not None else cfg["activeEnv"]
    if not key:
        return None
    return cfg["environments"].get(key)


def add_environment(name: str, env: dict[str, Any]) -> dict[str, Any]:
    """Register or update an environment.

    Takes no secret: a clientSecret added to config.json by hand is kept. readOnly is
    kept unless the caller states it (true or false), so an update can never switch
    read-only protection off by omission.
    """
    stored = _read_stored()
    existing = stored["environments"].get(name) or {}
    read_only = env.get("readOnly") if env.get("readOnly") is not None else existing.get("readOnly")
    new_env: dict[str, Any] = {
        "apiBaseUrl": str(env["apiBaseUrl"]).rstrip("/"),
        "oauthRealm": env["oauthRealm"],
        "oauthClientId": env["oauthClientId"],
    }
    if env.get("authMode") == "client_credentials":
        new_env["authMode"] = "client_credentials"
    if read_only:
        new_env["readOnly"] = True
    if existing.get("clientSecret"):
        new_env["clientSecret"] = existing["clientSecret"]
    stored["environments"][name] = new_env
    if not stored["activeEnv"]:
        stored["activeEnv"] = name
    _write_stored(stored)
    return _without_secrets(stored)


def use_environment(name: str) -> dict[str, Any]:
    stored = _read_stored()
    if name not in stored["environments"]:
        raise ValueError(f"Environment '{name}' not found. Add it with add_ifs_environment first.")
    stored["activeEnv"] = name
    _write_stored(stored)
    return _without_secrets(stored)


def remove_environment(name: str) -> dict[str, Any]:
    stored = _read_stored()
    stored["environments"].pop(name, None)
    if stored["activeEnv"] == name:
        remaining = list(stored["environments"])
        stored["activeEnv"] = remaining[0] if len(remaining) == 1 else None
    _write_stored(stored)
    return _without_secrets(stored)


def get_config_diagnostics() -> dict[str, str]:
    """Where this process resolved its home folder and config file (no secrets)."""
    return {"homeDir": str(Path.home()), "configFile": str(config_file())}


def client_secret_env_var(name: str) -> str:
    return "IFS_CLIENT_SECRET_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


def client_secret_source(name: str) -> SecretSource:
    """Where an environment's client secret is configured, never the value."""
    if os.environ.get(client_secret_env_var(name)):
        return "env"
    if (_read_stored()["environments"].get(name) or {}).get("clientSecret"):
        return "config"
    return "missing"


def get_client_secret(name: str) -> str | None:
    """The client secret: env var first, then config.json.

    ONLY auth.oauth.OAuthManager.client_credentials_token may call this. Never log,
    return or put the result in tool output.
    """
    from_env = os.environ.get(client_secret_env_var(name))
    if from_env:
        return from_env
    return (_read_stored()["environments"].get(name) or {}).get("clientSecret") or None
