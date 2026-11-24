"""Authenticated calls to IFS Cloud projections.

Guards that apply to every tool that sends a request:
- the endpoint must stay on the environment's own host (the bearer token never leaves it);
- only an allowlist of request headers is accepted from the model;
- read-only environments accept GET only, checked against the environment the request
  actually goes to.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx

from . import config, endpoints
from .auth import sessions
from .auth.oauth import LoginRequired, OAuthManager, TokenRequestError

ALLOWED_REQUEST_HEADERS = ("if-match", "if-none-match", "x-ifs-content-disposition")
REQUEST_TIMEOUT_S = 120.0

_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def disallowed_headers(headers: dict[str, Any] | None) -> list[str]:
    """Caller header names that are not allowed, or [] if all are fine."""
    if not headers:
        return []
    return [k for k in headers if k.lower() not in ALLOWED_REQUEST_HEADERS]


def _origin(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return None
    port = parts.port
    default = {"http": 80, "https": 443}.get(parts.scheme)
    host = parts.hostname.lower()
    return parts.scheme.lower(), f"{host}:{port if port is not None else default}"


def build_api_url(base: str, endpoint: Any) -> str | None:
    """base + endpoint, or None if the result would not stay on the base URL's host.

    The endpoint comes from the model, so it must never change where the token goes:
    base + "@evil.com/x" and a protocol-relative "//evil.com" both point elsewhere.
    """
    if not base or not isinstance(endpoint, str):
        return None
    if not endpoint.startswith("/") or endpoint.startswith("//"):
        return None
    if _BAD_CHARS.search(endpoint):
        return None
    try:
        full = _origin(base + endpoint)
        own = _origin(base)
    except ValueError:
        return None
    if full is None or own is None or full != own:
        return None
    return base + endpoint


def _auth_required(message: str, status: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"success": False}
    if status is not None:
        result["status"] = status
    result["error"] = "authentication_required"
    result["message"] = message
    return result


async def call_protected_api(
    oauth: OAuthManager,
    endpoint: str,
    method: str,
    session_id: str | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make an authenticated call. Returns {success, status?, data?, error?, message?, details?}."""
    session_id = session_id or sessions.get_current_session_id()
    if not session_id:
        return _auth_required(
            "No active session. Call the start_oauth tool now to open the login window - do not ask the user to do this manually."
        )

    target = config.get_environment(session_id)
    if target and target.get("readOnly") and str(method).upper() != "GET":
        return {
            "success": False,
            "error": "read_only_environment",
            "message": f"Environment '{session_id}' is marked read-only; {method} is blocked. Only GET requests are allowed.",
        }

    url = build_api_url(endpoints.get_api_base_url_for_key(session_id), endpoint)
    if not url:
        return {
            "success": False,
            "error": "invalid_endpoint",
            "message": "The endpoint must be a path on your IFS Cloud instance that starts with a single '/' (for example /main/ifsapplications/projection/v1/...). Full URLs and other hosts are not allowed.",
        }

    try:
        token = await anyio.to_thread.run_sync(oauth.get_access_token, session_id)
        # Server-set headers are applied last, case-insensitively, so caller headers can never override them.
        req_headers = httpx.Headers(headers or {})
        req_headers["Authorization"] = f"Bearer {token}"
        req_headers["Accept"] = "application/json"
        req_headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, follow_redirects=False) as client:
            resp = await client.request(method, url, headers=req_headers, json=body if body else None)
    except LoginRequired as exc:
        return _auth_required(
            f"{exc} Call the start_oauth tool now to open the login window - do not ask the user to do this manually."
        )
    except TokenRequestError as exc:
        # Failed to get a token: a 403 here is about the OAuth client, not a projection permission.
        return _http_failure(exc.status, exc.data, str(exc), from_token_endpoint=True)
    except httpx.HTTPError as exc:
        return _http_failure(None, None, f"{type(exc).__name__}: {exc}")

    data = _response_data(resp)
    if 200 <= resp.status_code < 300:
        return {"success": True, "status": resp.status_code, "data": data}
    return _http_failure(resp.status_code, data, f"Request failed with status code {resp.status_code}")


def _response_data(resp: httpx.Response) -> Any:
    if not resp.content:
        return ""
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _http_failure(
    status: int | None, data: Any, fallback_message: str, from_token_endpoint: bool = False
) -> dict[str, Any]:
    if status == 401:
        return _auth_required(
            "Session expired or unauthorised. Call the start_oauth tool now to re-authenticate - do not ask the user to do this manually.",
            status,
        )
    # 403: the token is valid but the IFS user lacks the permission set. A new login gets the
    # same user and the same 403, so asking for one only makes the agent loop.
    if status == 403 and not from_token_endpoint:
        return _failure(
            status, "permission_denied", data,
            "The IFS user is signed in but has no permission for this projection or action. "
            "Do not call start_oauth again - logging in as the same user will not help. "
            "Tell the user which endpoint was refused and that their IFS administrator must grant "
            "the permission set for it (for a client_credentials environment: the service user's permission sets).",
        )
    # 412: the If-Match etag no longer matches - someone changed the record since it was read.
    if status == 412 and not from_token_endpoint:
        return _failure(
            status, "precondition_failed", data,
            "The record was changed in IFS after you read it, so its If-Match etag is out of date and nothing was saved. "
            "Do not retry with the same etag and do not drop the If-Match header. "
            "GET the record again, show the user what changed, and retry with the new @odata.etag only if the user agrees.",
        )
    result: dict[str, Any] = {"success": False}
    if status is not None:
        result["status"] = status
    result["error"] = "API call failed"
    result["message"] = data if data else fallback_message
    result["details"] = (data.get("error") if isinstance(data, dict) else None) or None
    return result


def _failure(status: int, error: str, data: Any, message: str) -> dict[str, Any]:
    """A failure the agent should handle in a specific way; IFS's own error body goes in details."""
    return {
        "success": False,
        "status": status,
        "error": error,
        "message": message,
        "details": (data.get("error") if isinstance(data, dict) else None) or data or None,
    }
