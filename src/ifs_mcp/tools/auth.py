"""start_oauth and get_session_info."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio

from .. import config, endpoints
from ..auth import sessions
from ..auth.callback_server import start_callback_server
from ..auth.oauth import OAuthManager
from ..ui import login_page
from ..util import json_result, now_ms

START_OAUTH_DEFINITION = {
    "name": "start_oauth",
    "description": "Start OAuth 2.0 authentication flow - opens a login window in the browser. Call this automatically whenever an API tool returns an authentication_required error or session expiry. Do not ask the user to trigger this manually.",
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    "inputSchema": {
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "description": "Force re-authentication even if there's an active session"},
        },
    },
}


def _open_in_browser(path: str) -> None:
    """Open a local file with the default handler. The path is passed as an argument, never through a shell."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        print(f"Failed to open browser: {exc}", file=sys.stderr)


def create_login_page(auth_url: str, state: str, environment: str) -> str:
    """Write the start page to the temp folder and return its path."""
    temp_dir = Path(tempfile.gettempdir()) / "ifs-mcp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    html_path = temp_dir / f"login-{state}.html"
    host = urlsplit(auth_url).netloc
    read_only = bool((config.get_environment(environment) or {}).get("readOnly"))
    html_path.write_text(login_page(auth_url, environment, host, read_only), encoding="utf-8")
    return str(html_path)


async def start_oauth_handler(args: dict[str, Any], oauth: OAuthManager) -> dict[str, Any]:
    force = bool(args.get("force", False))

    if not config.get_active_session_key():
        names = list(config.list_environments()["environments"])
        return json_result({
            "error": "no_environment_configured" if not names else "no_environment_selected",
            "message": (
                "No IFS environment is configured. Ask the user for their IFS Cloud URL, OAuth realm, and client ID, then call add_ifs_environment."
                if not names else "No IFS environment is selected. Ask the user which one to use, then call use_ifs_environment."
            ),
            "environments": names,
        }, is_error=True)

    active = config.get_active_session_key()
    if endpoints.get_oauth_params_for_key(active).auth_mode == "client_credentials":
        try:
            await anyio.to_thread.run_sync(oauth.client_credentials_token, active)
        except Exception as exc:
            return json_result({"status": "client_credentials_failed", "environment": active, "message": str(exc)},
                               is_error=True)
        data = sessions.get_token(active)
        return json_result({
            "status": "authenticated",
            "environment": active,
            "authMode": "client_credentials",
            "expiresInMinutes": (data["expiresAt"] - now_ms()) // 60000 if data else 0,
            "message": "Authenticated via client credentials (service account). No browser login required.",
        })

    if not force:
        sid = sessions.get_current_session_id()
        data = sessions.get_token(sid) if sid else None
        if data and data["expiresAt"] >= now_ms():
            return json_result({
                "status": "already_authenticated",
                "message": "You already have an active session",
                "sessionId": sid,
                "expiresInMinutes": (data["expiresAt"] - now_ms()) // 60000,
                "hint": "Use force:true to re-authenticate",
            })

    auth_url, state = oauth.start_auth_flow()
    start_callback_server(oauth)
    html_path = create_login_page(auth_url, state, active)
    _open_in_browser(html_path)
    return json_result({
        "status": "login_window_opened",
        "message": "Login window opened in your default browser",
        "state": state,
        "instructions": "Please complete the authentication in the browser window. After successful login, you'll be redirected back and your session will be saved automatically.",
        "loginPagePath": html_path,
    })


GET_SESSION_INFO_DEFINITION = {
    "name": "get_session_info",
    "description": "Get information about the current saved session for the active IFS environment, including which environment is active and expiration status.",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    "inputSchema": {"type": "object", "properties": {}},
}


async def get_session_info_handler(_args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    active = config.get_active_env_name()
    sid = sessions.get_current_session_id()
    if not sid:
        return json_result({
            "authenticated": False,
            "activeEnvironment": active,
            "message": (
                "No active session found for the selected environment. Please use start_oauth to authenticate."
                if active else "No IFS environment selected. Use list_ifs_environments and use_ifs_environment first."
            ),
        })
    data = sessions.get_token(sid)
    if not data:
        return json_result({
            "authenticated": False,
            "message": "Session ID found but session data is missing. Please re-authenticate.",
        })
    now = now_ms()
    expired = data["expiresAt"] < now
    expires_in = (data["expiresAt"] - now) // 1000
    return json_result({
        "authenticated": True,
        "activeEnvironment": active,
        "sessionId": sid,
        "expiresIn": 0 if expired else expires_in,
        "expiresInMinutes": 0 if expired else expires_in // 60,
        "isExpired": expired,
        "canRefresh": bool(data.get("refreshToken")),
        "userId": data.get("userId"),
        "message": (
            "Session expired but can be refreshed automatically on next API call"
            if expired else f"Session active and valid for {expires_in // 60} more minutes"
        ),
    })


START_OAUTH = (START_OAUTH_DEFINITION, start_oauth_handler)
GET_SESSION_INFO = (GET_SESSION_INFO_DEFINITION, get_session_info_handler)
