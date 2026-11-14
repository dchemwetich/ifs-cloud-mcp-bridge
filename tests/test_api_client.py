"""Rules 1-3, 9: host guard, header allowlist, read-only, auth errors."""

import json

import anyio
import httpx
import pytest
from conftest import ENV

from ifs_mcp import api_client
from ifs_mcp.api_client import build_api_url, disallowed_headers
from ifs_mcp.auth import sessions
from ifs_mcp.auth.oauth import OAuthManager
from ifs_mcp.util import now_ms

BASE = "https://ifs.example"


@pytest.mark.parametrize(
    "endpoint",
    ["@evil.com/x", "//evil.com/x", "evil.com/x", "https://evil.com/x", "/a\\b", "/a\nb", "/a\x7f", "", None, 5],
)
def test_build_api_url_rejects_other_hosts_and_bad_paths(endpoint):
    assert build_api_url(BASE, endpoint) is None


def test_build_api_url_accepts_plain_paths():
    url = "/main/ifsapplications/projection/v1/X.svc/Set?$filter=a eq 'b@c.com'"
    assert build_api_url(BASE, url) == BASE + url
    assert build_api_url(BASE, "/@evil.com") == BASE + "/@evil.com"  # still a path on our host
    assert build_api_url("", "/x") is None


def test_header_allowlist():
    assert disallowed_headers(None) == []
    assert disallowed_headers({"If-Match": "*", "X-IFS-Content-Disposition": "a"}) == []
    assert disallowed_headers({"Authorization": "x", "if-none-match": "y", "Host": "z"}) == ["Authorization", "Host"]


@pytest.fixture
def mock_http(monkeypatch):
    """Route api_client's AsyncClient through a mock transport; returns the captured requests."""
    seen: list[httpx.Request] = []
    responses: list[httpx.Response] = []
    real = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json={"value": []})

    monkeypatch.setattr(api_client.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen, responses


def _login(key="dev"):
    sessions.set_token(key, {"accessToken": "tok", "refreshToken": "r", "expiresAt": now_ms() + 3_600_000,
                             "issuedAt": now_ms(), "userId": key})


def _call(**kw):
    return anyio.run(lambda: api_client.call_protected_api(OAuthManager(), **kw))


def test_server_headers_override_caller_headers(write_config, mock_http):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    _login()
    seen, _ = mock_http
    res = _call(endpoint="/x", method="GET", headers={"authorization": "Bearer stolen", "If-Match": "W/1"})
    assert res["success"]
    req = seen[0]
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["if-match"] == "W/1"
    assert str(req.url) == "https://ifs.example/x"


def test_read_only_enforced_on_target_env(write_config, mock_http):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV, "prod": {**ENV, "readOnly": True}}})
    _login("prod")
    seen, _ = mock_http
    res = _call(endpoint="/x", method="PATCH", session_id="prod", body={"a": 1})
    assert res["error"] == "read_only_environment" and not seen
    assert _call(endpoint="/x", method="GET", session_id="prod")["success"]


@pytest.mark.parametrize("status", [401, 403])
def test_unauthorised_becomes_authentication_required(write_config, mock_http, status):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    _login()
    mock_http[1].append(httpx.Response(status, json={"error": "nope"}))
    res = _call(endpoint="/x", method="GET")
    assert res["error"] == "authentication_required" and res["status"] == status
    assert "start_oauth" in res["message"]


def test_api_error_shape(write_config, mock_http):
    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    _login()
    mock_http[1].append(httpx.Response(404, json={"error": {"code": "NOT_FOUND"}}))
    res = _call(endpoint="/x", method="GET")
    assert res == {"success": False, "status": 404, "error": "API call failed",
                   "message": {"error": {"code": "NOT_FOUND"}}, "details": {"code": "NOT_FOUND"}}


def test_no_session_asks_for_login(home):
    res = _call(endpoint="/x", method="GET")
    assert res["error"] == "authentication_required"


def test_large_response_summary(write_config, mock_http):
    from ifs_mcp.tools import api

    write_config({"activeEnv": "dev", "environments": {"dev": ENV}})
    _login()
    rows = [{"Id": i, "Text": "x" * 200, "B": True} for i in range(800)]
    mock_http[1].append(httpx.Response(200, json={"value": rows}))
    out = anyio.run(lambda: api.call_handler({"endpoint": "/x", "method": "GET"}, OAuthManager()))
    summary = json.loads(out["content"][0]["text"])
    assert summary["total_records"] == 800
    assert summary["available_fields"] == ["Id", "Text", "B"]
    assert "$select=Id,Text,B" in summary["options"]["select_fields"]
