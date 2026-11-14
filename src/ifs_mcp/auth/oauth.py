"""OAuth 2.0 against IFS Cloud (Keycloak): PKCE login, refresh, client credentials.

Token requests are synchronous (httpx.Client) because the browser callback arrives on
the callback server's thread. Async callers wrap them in anyio.to_thread.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .. import config, endpoints
from ..util import now_ms
from . import sessions

PENDING_AUTH_TTL_S = 10 * 60
TOKEN_TIMEOUT_S = 30.0

# Renew at 10 % of the token lifetime before expiry, bounded to 5-30 s. Sessions saved
# without issuedAt use the old fixed 300 s buffer once.
MIN_REFRESH_MARGIN_MS = 5_000
MAX_REFRESH_MARGIN_MS = 30_000
LEGACY_SESSION_FALLBACK_MARGIN_MS = 300_000


class LoginRequired(RuntimeError):
    """The user must sign in again in the browser (no session, or it can no longer be refreshed)."""


class TokenRequestError(Exception):
    """A token endpoint call failed. Carries only status and the server's error text."""

    def __init__(self, message: str, status: int | None = None, data: Any = None):
        super().__init__(message)
        self.status = status
        self.data = data


def generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def refresh_margin_ms(session: dict[str, Any]) -> float:
    issued = session.get("issuedAt")
    if issued is None:
        return LEGACY_SESSION_FALLBACK_MARGIN_MS
    lifetime = session["expiresAt"] - issued
    return max(MIN_REFRESH_MARGIN_MS, min(MAX_REFRESH_MARGIN_MS, lifetime * 0.1))


def _post_token(token_url: str, form: dict[str, str]) -> dict[str, Any]:
    """POST a form to the token endpoint. Errors never include the request body."""
    try:
        resp = httpx.post(token_url, data=form, timeout=TOKEN_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise TokenRequestError(f"Token request failed: {type(exc).__name__}") from None
    if resp.status_code >= 300:
        try:
            data: Any = resp.json()
        except ValueError:
            data = resp.text
        raise TokenRequestError(f"Request failed with status code {resp.status_code}", resp.status_code, data)
    return resp.json()


class OAuthManager:
    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _purge_expired(self) -> None:
        cutoff = time.monotonic() - PENDING_AUTH_TTL_S
        for state in [s for s, p in self._pending.items() if p["created"] < cutoff]:
            del self._pending[state]

    def start_auth_flow(self) -> tuple[str, str]:
        """Return (auth_url, state). The flow is bound to the environment active now."""
        session_key = config.get_active_session_key()
        if not session_key:
            raise RuntimeError(
                "No IFS environment selected. Add one with add_ifs_environment, then choose it with use_ifs_environment."
            )
        state = secrets.token_hex(16)
        verifier = generate_code_verifier()
        with self._lock:
            self._purge_expired()
            self._pending[state] = {"codeVerifier": verifier, "sessionKey": session_key, "created": time.monotonic()}
        params = {
            "client_id": endpoints.get_oauth_client_id(),
            "redirect_uri": endpoints.REDIRECT_URI,
            "response_type": "code",
            "scope": endpoints.SCOPE,
            "state": state,
            "code_challenge": generate_code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        return f"{endpoints.authorization_url()}?{urlencode(params)}", state

    def exchange_code(self, code: str, state: str) -> str:
        """Swap the authorization code for tokens; returns the session key."""
        with self._lock:
            self._purge_expired()
            pending = self._pending.pop(state, None)
        if not pending:
            raise RuntimeError("Invalid state parameter")
        key = pending["sessionKey"]
        params = endpoints.get_oauth_params_for_key(key)
        data = _post_token(
            params.token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": endpoints.REDIRECT_URI,
                "client_id": params.client_id,
                "code_verifier": pending["codeVerifier"],
            },
        )
        now = now_ms()
        sessions.set_token(
            key,
            {
                "accessToken": data["access_token"],
                "refreshToken": data.get("refresh_token"),
                "expiresAt": now + int(data["expires_in"]) * 1000,
                "issuedAt": now,
                "userId": key,
            },
        )
        return key

    def refresh_access_token(self, key: str) -> None:
        session = sessions.get_token(key)
        if not session or not session.get("refreshToken"):
            raise LoginRequired("No refresh token available")
        params = endpoints.get_oauth_params_for_key(key)
        try:
            data = _post_token(
                params.token_url,
                {"grant_type": "refresh_token", "refresh_token": session["refreshToken"], "client_id": params.client_id},
            )
        except TokenRequestError as exc:
            # 400/401 from the token endpoint (e.g. invalid_grant): the refresh token is expired or
            # revoked. Drop the dead session so status checks stop reporting it as refreshable.
            if exc.status in (400, 401):
                sessions.remove_session(key)
                detail = exc.data if isinstance(exc.data, dict) else {}
                reason = detail.get("error_description") or detail.get("error") or str(exc)
                raise LoginRequired(f"Saved login for '{key}' can no longer be refreshed ({reason}).") from None
            raise
        now = now_ms()
        updated = {
            "accessToken": data["access_token"],
            "refreshToken": data.get("refresh_token") or session["refreshToken"],
            "expiresAt": now + int(data["expires_in"]) * 1000,
            "issuedAt": now,
            "userId": session.get("userId", key),
        }
        sessions.set_token(key, updated)
        sessions.save_session(key, updated)

    def client_credentials_token(self, key: str) -> None:
        """Get a token with the client credentials grant (no browser, no refresh token)."""
        params = endpoints.get_oauth_params_for_key(key)
        # The one place a client secret is read. Never logged, returned or put in an error.
        client_secret = config.get_client_secret(key)
        if not client_secret:
            raise RuntimeError(
                f"Environment '{key}' uses client_credentials but no client secret is configured. "
                f"Never send the secret through chat. Set the {config.client_secret_env_var(key)} environment variable, "
                f'or add "clientSecret" to environments.{key} in {config.get_config_diagnostics()["configFile"]}, then retry.'
            )
        try:
            data = _post_token(
                params.token_url,
                {"grant_type": "client_credentials", "client_id": params.client_id, "client_secret": client_secret},
            )
        except TokenRequestError as exc:
            detail = "request failed"
            if isinstance(exc.data, dict):
                detail = exc.data.get("error_description") or exc.data.get("error") or detail
            status = f" (HTTP {exc.status})" if exc.status else ""
            raise RuntimeError(f"Token request for environment '{key}' failed{status}: {detail}") from None
        now = now_ms()
        token = {
            "accessToken": data["access_token"],
            "expiresAt": now + int(data["expires_in"]) * 1000,
            "issuedAt": now,
            "userId": key,
        }
        sessions.set_token(key, token)
        sessions.save_session(key, token)

    def get_access_token(self, key: str) -> str:
        """A valid access token for the session, renewing it first if needed."""
        mode = endpoints.get_oauth_params_for_key(key).auth_mode
        session = sessions.get_token(key)
        if not session:
            if mode == "client_credentials":
                self.client_credentials_token(key)
                return sessions.get_token(key)["accessToken"]
            raise LoginRequired("No session found. Please authenticate first.")
        if session["expiresAt"] < now_ms() + refresh_margin_ms(session):
            if mode == "client_credentials":
                self.client_credentials_token(key)
            else:
                self.refresh_access_token(key)
            return sessions.get_token(key)["accessToken"]
        return session["accessToken"]
