"""add / list / use / remove_ifs_environment."""

from __future__ import annotations

from typing import Any

from .. import config
from ..auth import sessions
from ..util import json_result, now_ms

# Argument names that would carry a secret (case-insensitive, ignoring _ and -).
_SECRET_ARG_NAMES = {"clientsecret", "secret", "password", "apikey"}


def _error(message: str) -> dict[str, Any]:
    return json_result({"error": message}, is_error=True)


# --- add_ifs_environment -----------------------------------------------------

ADD_DEFINITION = {
    "name": "add_ifs_environment",
    "description": (
        "Register (or update) a named IFS Cloud environment with its URL, OAuth realm, and client ID. "
        "The first environment added becomes the active one automatically. "
        "Use this during setup when no environment is configured yet, or to add another instance (e.g. test, dev). "
        "Auth mode defaults to interactive browser login (authorization_code). Set authMode to 'client_credentials' for headless/service-account auth (works without a browser) - this needs a confidential client, and all calls run as the integration user rather than the end user. "
        "NEVER ask the user for a client secret and never accept one in chat: this tool takes no secret. For client_credentials the user supplies it themselves, outside the conversation - via the IFS_CLIENT_SECRET_<NAME> environment variable, or by editing config.json (the response says exactly how). If the user pastes a secret into chat anyway, do not use or repeat it; tell them to rotate it in IFS IAM."
    ),
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short name for this environment, e.g. 'prod', 'test', 'dev'."},
            "apiBaseUrl": {"type": "string", "description": "Base URL of the IFS Cloud instance, e.g. https://your-tenant.ifs.cloud"},
            "oauthRealm": {"type": "string", "description": "The IFS OAuth realm name."},
            "oauthClientId": {
                "type": "string",
                "description": "The IFS OAuth 2.0 client ID. A public client for authorization_code, or a confidential client for client_credentials (max 20 characters in IFS).",
            },
            "authMode": {
                "type": "string",
                "enum": ["authorization_code", "client_credentials"],
                "description": "Authentication mode. 'authorization_code' (default) = interactive browser login as the end user. 'client_credentials' = headless service-account login (no browser); the secret is supplied by the user outside chat.",
            },
            "readOnly": {
                "type": "boolean",
                "description": "Optional. When true, every API tool (call_protected_api and export_api_data) blocks non-GET methods for this environment (recommended for production). When updating an existing environment, omit it to keep the current setting; pass false only if the user asked to allow writes.",
            },
        },
        "required": ["name", "apiBaseUrl", "oauthRealm", "oauthClientId"],
    },
}


def _find_secret_arg(args: dict[str, Any]) -> str | None:
    for key in args:
        if key.lower().replace("_", "").replace("-", "") in _SECRET_ARG_NAMES:
            return key
    return None


async def add_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    # Refuse before touching anything else. The value is never read or echoed.
    if _find_secret_arg(args):
        return _error(
            "This tool does not accept a client secret, and secrets must not be sent through chat. "
            "Nothing was saved. Register the environment without it; the response will explain how to add the secret yourself "
            "(environment variable or config.json). If you already pasted a secret into a chat, rotate it in IFS IAM."
        )
    name, base, realm, client_id = (args.get(k) for k in ("name", "apiBaseUrl", "oauthRealm", "oauthClientId"))
    auth_mode, read_only = args.get("authMode"), args.get("readOnly")
    if not name or not base or not realm or not client_id:
        return _error("name, apiBaseUrl, oauthRealm and oauthClientId are all required.")
    if auth_mode and auth_mode not in ("authorization_code", "client_credentials"):
        return _error("authMode must be 'authorization_code' or 'client_credentials'.")

    cfg = config.add_environment(name, {
        "apiBaseUrl": base, "oauthRealm": realm, "oauthClientId": client_id, "authMode": auth_mode,
        "readOnly": read_only if isinstance(read_only, bool) else None,
    })
    is_cc = auth_mode == "client_credentials"
    is_active = cfg["activeEnv"] == name

    secret: dict[str, Any] | None = None
    if is_cc:
        source = config.client_secret_source(name)
        env_var = config.client_secret_env_var(name)
        cfg_file = config.get_config_diagnostics()["configFile"]
        if source == "missing":
            secret = {
                "status": "missing",
                "action_required": (
                    "Ask the user to add the client secret themselves - do NOT ask them to paste it here. "
                    f"Option 1: set the {env_var} environment variable before the host starts. "
                    f'Option 2: open {cfg_file} and add "clientSecret": "<secret>" inside environments.{name}. '
                    "Changes to config.json take effect on the next call; no restart needed. "
                    "Then call start_oauth to confirm."
                ),
                "envVar": env_var,
                "configFile": cfg_file,
                "configSnippet": {"environments": {name: {"clientSecret": "<paste the secret here yourself - not in chat>"}}},
            }
        else:
            secret = {"status": "configured", "source": source}

    if is_active:
        hint = (
            "This is now the active environment. Once the client secret is configured (see clientSecret above) it authenticates automatically on the first call - start_oauth is optional and will just pre-fetch a token."
            if is_cc else "This is now the active environment. Call start_oauth to authenticate."
        )
    else:
        tail = " (it authenticates automatically once its secret is configured)." if is_cc else ", then start_oauth."
        hint = f"Run use_ifs_environment with '{name}' to switch to it{tail}"

    payload: dict[str, Any] = {
        "success": True,
        "message": f"Environment '{name}' saved.",
        "authMode": "client_credentials" if is_cc else "authorization_code",
        "activeEnvironment": cfg["activeEnv"],
    }
    if secret:
        payload["clientSecret"] = secret
    payload["hint"] = hint
    return json_result(payload)


# --- list_ifs_environments ---------------------------------------------------

LIST_DEFINITION = {
    "name": "list_ifs_environments",
    "description": (
        "List all configured IFS Cloud environments, showing which one is active and whether each is currently authenticated. "
        "Use this to show the user their options before they choose an environment to work with."
    ),
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    "inputSchema": {"type": "object", "properties": {}},
}


async def list_handler(_args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    cfg = config.list_environments()
    saved = sessions.load_sessions()
    now = now_ms()
    envs = []
    for name, env in cfg["environments"].items():
        session = saved.get(name)
        status = "not_authenticated"
        if session:
            status = "authenticated" if session.get("expiresAt", 0) > now else "expired"
        item: dict[str, Any] = {
            "name": name,
            "apiBaseUrl": env.get("apiBaseUrl"),
            "oauthRealm": env.get("oauthRealm"),
            "authMode": config.auth_mode_of(env),
        }
        if config.auth_mode_of(env) == "client_credentials":
            source = config.client_secret_source(name)
            item["clientSecretSource"] = source
            if source == "missing":
                item["clientSecretEnvVar"] = config.client_secret_env_var(name)
        item.update({"readOnly": bool(env.get("readOnly")), "active": cfg["activeEnv"] == name, "authStatus": status})
        envs.append(item)

    payload: dict[str, Any] = {
        "activeEnvironment": cfg["activeEnv"],
        "environments": envs,
        "diagnostics": config.get_config_diagnostics(),
    }
    if not envs:
        payload["hint"] = (
            "No environments configured. Use add_ifs_environment to add one. If you expected environments to already be here, check `diagnostics.configFile` above - a host that launches this process in an unexpected context (different user profile, WSL vs native Windows, etc.) can silently resolve a different config.json than the one you edited."
        )
    return json_result(payload)


# --- use_ifs_environment -----------------------------------------------------

USE_DEFINITION = {
    "name": "use_ifs_environment",
    "description": (
        "Select which IFS Cloud environment subsequent IFS calls target. The selection persists until changed. "
        "Call this when the user says which environment to work with (e.g. 'use test', 'switch to prod')."
    ),
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the environment to activate (must already exist - see list_ifs_environments).",
            },
        },
        "required": ["name"],
    },
}


async def use_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    name = args.get("name")
    try:
        config.use_environment(name)
    except ValueError as exc:
        return json_result({"error": str(exc), "environments": list(config.list_environments()["environments"])},
                           is_error=True)

    session = sessions.load_sessions().get(name)
    authed = bool(session) and session.get("expiresAt", 0) > now_ms()
    mode = config.auth_mode_of(config.get_environment(name))
    if authed:
        hint = "Already authenticated for this environment. You can make IFS calls now."
    elif mode == "client_credentials":
        if config.client_secret_source(name) == "missing":
            hint = (
                f"This environment uses client credentials but has no client secret yet. Ask the user to set the "
                f"{config.client_secret_env_var(name)} environment variable or add \"clientSecret\" to this environment in config.json themselves - never through chat."
            )
        else:
            hint = "This environment uses client credentials - it authenticates automatically on the first IFS call. No browser login needed."
    else:
        hint = "Not authenticated for this environment yet - call start_oauth."
    return json_result({"success": True, "activeEnvironment": name, "authMode": mode, "authenticated": authed, "hint": hint})


# --- remove_ifs_environment --------------------------------------------------

REMOVE_DEFINITION = {
    "name": "remove_ifs_environment",
    "description": (
        "Delete a configured IFS Cloud environment and its saved authentication token. "
        "If the removed environment was active and only one other remains, that one becomes active; otherwise no environment is active."
    ),
    "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    "inputSchema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Name of the environment to remove."}},
        "required": ["name"],
    },
}


async def remove_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return json_result({"error": "name is required."}, is_error=True)
    cfg = config.remove_environment(name)
    sessions.remove_session(name)
    return json_result({
        "success": True,
        "message": f"Environment '{name}' removed.",
        "activeEnvironment": cfg["activeEnv"],
        "remaining": list(cfg["environments"]),
    })


ADD = (ADD_DEFINITION, add_handler)
LIST = (LIST_DEFINITION, list_handler)
USE = (USE_DEFINITION, use_handler)
REMOVE = (REMOVE_DEFINITION, remove_handler)
