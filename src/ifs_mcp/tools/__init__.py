"""Tool registry: (definition, handler) pairs in the order the server lists them."""

from __future__ import annotations

from . import api, auth, env, skills

TOOLS = [
    env.ADD,
    env.LIST,
    env.USE,
    env.REMOVE,
    auth.START_OAUTH,
    auth.GET_SESSION_INFO,
    api.CALL_PROTECTED_API,
    api.GET_API_GUIDE,
    api.EXPORT_API_DATA,
    skills.IMPORT_SKILL,
    skills.SAVE_SKILL,
    skills.PARSE_HAR_FILE,
    skills.READ_OPENAPI_FILE,
]
