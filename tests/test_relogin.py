"""An expired or missing login must ask the agent to sign in again, not fail as an API error."""

import json

import anyio
import pytest
from conftest import ENV

from ifs_mcp import api_client
from ifs_mcp.auth import oauth as oauth_mod
from ifs_mcp.auth import sessions
from ifs_mcp.auth.oauth import OAuthManager, TokenRequestError


def _call():
    return anyio.run(lambda: api_client.call_protected_api(OAuthManager(), endpoint="/x", method="GET"))


def test_rejected_refresh_asks_for_login_and_drops_session(write_config, monkeypatch, home):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    expired = {"accessToken": "old", "refreshToken": "R1", "expiresAt": 0, "issuedAt": 0, "userId": "dev"}
    sessions.set_token("dev", expired)
    sessions.save_session("dev", expired)

    def refused(url, form):
        raise TokenRequestError("Request failed with status code 400", 400,
                                {"error": "invalid_grant", "error_description": "Token is not active"})

    monkeypatch.setattr(oauth_mod, "_post_token", refused)
    res = _call()
    assert res["error"] == "authentication_required"
    assert "Token is not active" in res["message"] and "start_oauth" in res["message"]
    assert sessions.get_token("dev") is None
    assert "dev" not in json.loads((home / ".ifs-mcp" / "session.json").read_text())


@pytest.mark.parametrize("status", [500, 403, None])
def test_token_server_outage_is_not_a_login_problem(write_config, monkeypatch, status):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    sessions.set_token("dev", {"accessToken": "old", "refreshToken": "R1", "expiresAt": 0, "issuedAt": 0, "userId": "dev"})

    def down(url, form):
        raise TokenRequestError("Token request failed", status, None)

    monkeypatch.setattr(oauth_mod, "_post_token", down)
    res = _call()
    assert res["error"] == "API call failed"
    assert sessions.get_token("dev") is not None  # session kept: a retry may work


def test_no_saved_session_asks_for_login(write_config):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    res = _call()
    assert res["error"] == "authentication_required"
    assert "No session found" in res["message"]
