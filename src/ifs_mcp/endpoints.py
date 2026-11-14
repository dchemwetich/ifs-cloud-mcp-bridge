"""Base URL and OAuth endpoints per environment.

A session key is an environment name (or "default" in legacy env-var mode). URLs are
derived from the same key as the token, so a token is never paired with another host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import config

REDIRECT_URI = "http://localhost:3000/oauth/callback"
SCOPE = "openid"


def get_api_base_url() -> str:
    from_env = os.environ.get("API_BASE_URL")
    if from_env:
        return from_env.rstrip("/")
    env = config.get_environment()
    return ((env or {}).get("apiBaseUrl") or "").rstrip("/")


def get_oauth_realm() -> str:
    return os.environ.get("OAUTH_REALM") or (config.get_environment() or {}).get("oauthRealm") or ""


def get_oauth_client_id() -> str:
    return os.environ.get("OAUTH_CLIENT_ID") or (config.get_environment() or {}).get("oauthClientId") or ""


def authorization_url() -> str:
    return f"{get_api_base_url()}/auth/realms/{get_oauth_realm()}/protocol/openid-connect/auth"


def token_url() -> str:
    return f"{get_api_base_url()}/auth/realms/{get_oauth_realm()}/protocol/openid-connect/token"


def get_api_base_url_for_key(key: str | None) -> str:
    env = config.get_environment(key) if key else None
    if env:
        return env["apiBaseUrl"].rstrip("/")
    return get_api_base_url()


@dataclass(frozen=True)
class OAuthParams:
    client_id: str
    token_url: str
    auth_mode: config.AuthMode


def get_oauth_params_for_key(key: str | None) -> OAuthParams:
    env = config.get_environment(key) if key else None
    if env:
        base = env["apiBaseUrl"].rstrip("/")
        return OAuthParams(
            client_id=env["oauthClientId"],
            token_url=f"{base}/auth/realms/{env['oauthRealm']}/protocol/openid-connect/token",
            auth_mode=config.auth_mode_of(env),
        )
    # Legacy env-var mode: public client with PKCE only.
    return OAuthParams(client_id=get_oauth_client_id(), token_url=token_url(), auth_mode="authorization_code")
