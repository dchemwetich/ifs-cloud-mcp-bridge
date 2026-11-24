import json

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated home folder: config, sessions and exports go here."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for var in ("API_BASE_URL", "OAUTH_REALM", "OAUTH_CLIENT_ID", "SKILLS_DIR", "EXPORT_DIR"):
        monkeypatch.delenv(var, raising=False)
    from ifs_mcp.auth import sessions

    sessions.token_store.clear()
    yield tmp_path
    sessions.token_store.clear()


@pytest.fixture
def write_config(home):
    def _write(cfg):
        d = home / ".ifs-mcp"
        d.mkdir(exist_ok=True)
        (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    return _write


ENV = {"apiBaseUrl": "https://ifs.example", "oauthRealm": "realm1", "oauthClientId": "client1"}
