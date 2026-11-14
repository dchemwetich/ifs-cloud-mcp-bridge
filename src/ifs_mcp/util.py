"""Small helpers shared by the tools."""

from __future__ import annotations

import json
import math
import time
from typing import Any


def now_ms() -> int:
    """Current time in epoch milliseconds (the unit stored in session.json)."""
    return int(time.time() * 1000)


def dumps(obj: Any) -> str:
    """Pretty JSON, same layout as JSON.stringify(obj, null, 2)."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


def dumps_compact(obj: Any) -> str:
    """Compact JSON, same layout as JSON.stringify(obj)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def json_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return text_result(dumps(payload), is_error)


def js_string(value: Any) -> str:
    """String(value) as JavaScript would render a parsed JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value == int(value) and abs(value) < 1e21:
            return str(int(value))
        return repr(value)
    if isinstance(value, dict):
        return "[object Object]"
    if isinstance(value, list):
        return ",".join("" if v is None else js_string(v) for v in value)
    return str(value)
