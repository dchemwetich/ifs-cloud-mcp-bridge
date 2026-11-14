"""Rules 4-8, 15: config writes, secrets, OAuth, token renewal, callback page, session file."""

import ast
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import ENV

from ifs_mcp import config
from ifs_mcp.auth import oauth as oauth_mod
from ifs_mcp.auth import sessions
from ifs_mcp.auth.callback_server import _make_handler
from ifs_mcp.auth.oauth import OAuthManager, TokenRequestError, generate_code_challenge, refresh_margin_ms

PKG = Path(oauth_mod.__file__).resolve().parent.parent


# --- config (rule 5) ---------------------------------------------------------

def test_first_env_becomes_active_and_url_trimmed(home):
    cfg = config.add_environment("dev", {**ENV, "apiBaseUrl": "https://ifs.example///"})
    assert cfg["activeEnv"] == "dev"
    assert cfg["environments"]["dev"]["apiBaseUrl"] == "https://ifs.example"
    config.add_environment("test", ENV)
    assert config.get_active_env_name() == "dev"


def test_add_keeps_hand_added_secret_and_read_only(write_config, home):
    write_config({"activeEnv": "p", "environments": {"p": {**ENV, "readOnly": True, "clientSecret": "s3cret"}}})
    cfg = config.add_environment("p", {**ENV, "oauthRealm": "r2"})
    assert "clientSecret" not in cfg["environments"]["p"]
    stored = json.loads((home / ".ifs-mcp" / "config.json").read_text())
    assert stored["environments"]["p"]["clientSecret"] == "s3cret"
    assert stored["environments"]["p"]["readOnly"] is True
    config.add_environment("p", {**ENV, "readOnly": False})
    assert "readOnly" not in config.get_environment("p")


def test_remove_active_env_selects_only_remaining(home):
    for n in ("a", "b", "c"):
        config.add_environment(n, ENV)
    assert config.remove_environment("a")["activeEnv"] is None
    config.use_environment("b")
    assert config.remove_environment("b")["activeEnv"] == "c"
    with pytest.raises(ValueError):
        config.use_environment("zzz")


# --- secrets (rule 4) --------------------------------------------------------

def test_only_oauth_module_reads_the_secret():
    callers = []
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "get_client_secret":
                callers.append(f.relative_to(PKG).as_posix())
            if isinstance(node, ast.Name) and node.id == "get_client_secret":
                callers.append(f.relative_to(PKG).as_posix())
    assert set(callers) == {"auth/oauth.py"}


def test_secret_source_and_env_var(write_config, monkeypatch):
    write_config({"activeEnv": "svc", "environments": {"svc": {**ENV, "authMode": "client_credentials"}}})
    assert config.client_secret_env_var("my-env.1") == "IFS_CLIENT_SECRET_MY_ENV_1"
    assert config.client_secret_source("svc") == "missing"
    monkeypatch.setenv("IFS_CLIENT_SECRET_SVC", "x")
    assert config.client_secret_source("svc") == "env"


def test_client_credentials_error_never_contains_secret(write_config, monkeypatch):
    write_config({"activeEnv": "svc", "environments": {"svc": {**ENV, "authMode": "client_credentials",
                                                              "clientSecret": "TOPSECRET"}}})

    def fail(url, form):
        assert form["client_secret"] == "TOPSECRET"
        raise TokenRequestError("boom " + json.dumps(form), 401, {"error": "unauthorized_client"})

    monkeypatch.setattr(oauth_mod, "_post_token", fail)
    with pytest.raises(RuntimeError) as exc:
        OAuthManager().client_credentials_token("svc")
    assert "TOPSECRET" not in str(exc.value)
    assert "(HTTP 401): unauthorized_client" in str(exc.value)


def test_add_tool_refuses_secret_arguments(home):
    import anyio

    from ifs_mcp.tools.env import add_handler

    out = anyio.run(lambda: add_handler({"name": "x", **ENV, "Client-Secret": "zzz"}))
    assert out["isError"] and "zzz" not in out["content"][0]["text"]
    assert not (home / ".ifs-mcp" / "config.json").exists()


# --- OAuth (rules 6, 7) ------------------------------------------------------

def test_pkce_challenge_matches_rfc7636_example():
    assert generate_code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_auth_flow_is_bound_to_env_and_expires(write_config, monkeypatch):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV, "other": {**ENV, "oauthClientId": "c2"}}})
    m = OAuthManager()
    url, state = m.start_auth_flow()
    assert url.startswith("https://ifs.example/auth/realms/realm1/protocol/openid-connect/auth?")
    assert "code_challenge_method=S256" in url and "client_id=client1" in url and len(state) == 32
    config.use_environment("other")  # switching env mid-login must not move the token

    def ok(url, form):
        assert form["client_id"] == "client1" and form["code_verifier"]
        return {"access_token": "a", "refresh_token": "r", "expires_in": 300}

    monkeypatch.setattr(oauth_mod, "_post_token", ok)
    assert m.exchange_code("code", state) == "dev"
    assert sessions.get_token("dev")["accessToken"] == "a"
    with pytest.raises(RuntimeError, match="Invalid state"):
        m.exchange_code("code", state)

    _, old = m.start_auth_flow()
    m._pending[old]["created"] -= oauth_mod.PENDING_AUTH_TTL_S + 1
    with pytest.raises(RuntimeError, match="Invalid state"):
        m.exchange_code("code", old)


def test_refresh_margin():
    assert refresh_margin_ms({"expiresAt": 1_000}) == 300_000
    assert refresh_margin_ms({"issuedAt": 0, "expiresAt": 180_000}) == 18_000
    assert refresh_margin_ms({"issuedAt": 0, "expiresAt": 10_000}) == 5_000
    assert refresh_margin_ms({"issuedAt": 0, "expiresAt": 3_600_000}) == 30_000


def test_refresh_keeps_old_refresh_token_and_persists(write_config, monkeypatch, home):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    sessions.set_token("dev", {"accessToken": "old", "refreshToken": "R1", "expiresAt": 0, "issuedAt": 0, "userId": "dev"})
    monkeypatch.setattr(oauth_mod, "_post_token", lambda url, form: {"access_token": "new", "expires_in": 300})
    assert OAuthManager().get_access_token("dev") == "new"
    saved = json.loads((home / ".ifs-mcp" / "session.json").read_text())
    assert saved["dev"]["accessToken"] == "new" and saved["dev"]["refreshToken"] == "R1"


# --- callback page (rule 8) --------------------------------------------------

def test_callback_escapes_error_and_ignores_other_paths():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(OAuthManager()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/oauth/callback?error=%3Cscript%3Ex").read().decode()
        assert "&lt;script&gt;x" in body and "<script>" not in body
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/oauth/callback?code=c&state=bad").read().decode()
        assert "Invalid state parameter" in body
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/other")
    finally:
        server.shutdown()


# --- session file (rule 15) --------------------------------------------------

def test_session_file_round_trip_drops_missing_fields(home):
    sessions.save_session("dev", {"accessToken": "a", "refreshToken": None, "expiresAt": 5, "userId": "dev"})
    assert sessions.load_sessions() == {"dev": {"accessToken": "a", "expiresAt": 5, "userId": "dev"}}
    sessions.remove_session("dev")
    assert sessions.load_sessions() == {}
