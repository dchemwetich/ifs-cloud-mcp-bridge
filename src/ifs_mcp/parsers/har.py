"""Summarise the IFS projection calls in a browser HAR recording."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote

_PROJ = re.compile(r"/projection/v1/([^/]+)\.svc/(.+?)(\?|$)")


@dataclass
class OperationGroup:
    service: str
    entity_or_function: str
    method: str
    is_action: bool
    select_fields: list[str] = field(default_factory=list)
    filter_patterns: list[str] = field(default_factory=list)
    expand: list[str] = field(default_factory=list)
    orderby: list[str] = field(default_factory=list)
    top: int | None = None
    request_body_keys: list[str] = field(default_factory=list)
    response_sample: dict[str, str] | None = None
    call_count: int = 0


@dataclass
class ParsedHar:
    total_entries: int
    filtered_count: int
    skipped_count: int
    groups: list[OperationGroup]


def anonymise_filter(flt: str) -> str:
    """Replace literal values with placeholders; keep IfsApp enum values."""
    flt = re.sub(r"eq '(?!IfsApp)[^']*'", "eq '{value}'", flt)
    flt = re.sub(r"ne '(?!IfsApp)[^']*'", "ne '{value}'", flt)
    flt = re.sub(r"contains\(([^,]+),\s*'[^']*'\)", r"contains(\1, '{value}')", flt)
    flt = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "{date}", flt)
    flt = re.sub(r"\beq\s+[\d.]+\b", "eq {number}", flt)
    flt = re.sub(r"\bgt\s+[\d.]+\b", "gt {number}", flt)
    flt = re.sub(r"\blt\s+[\d.]+\b", "lt {number}", flt)
    return flt


def _entity_or_function(after_svc: str) -> tuple[str, bool]:
    parts = after_svc.split("/")
    first = parts[0].split("(")[0]
    action = next((p for p in parts if p.startswith("IfsApp.")), None)
    if action:
        return action.split(".")[-1], True
    return first, False


def _safe_json(text: str) -> dict[str, Any] | list[Any] | None:
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _js_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, (dict, list)):
        return "{object}"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    return "string"


def _type_skeleton(obj: Any) -> dict[str, str]:
    if isinstance(obj, dict):
        return {k: _js_type(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return {str(i): _js_type(v) for i, v in enumerate(obj)}
    return {}


def _flatten_sample(body: Any) -> dict[str, str]:
    value = body.get("value") if isinstance(body, dict) else None
    if isinstance(value, list) and value:
        return _type_skeleton(value[0])
    return _type_skeleton(body)


def _parse_int(text: str) -> int | None:
    m = re.match(r"\s*([+-]?\d+)", text)
    return int(m.group(1)) if m else None


def _add_unique(target: list[str], items: list[str]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)


def parse_har(file_path: str) -> ParsedHar:
    with open(file_path, encoding="utf-8") as fh:
        har = json.load(fh)
    entries = ((har or {}).get("log") or {}).get("entries") or []
    skipped = 0
    groups: dict[str, OperationGroup] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            entry = {}
        request = entry.get("request") or {}
        response = entry.get("response") or {}
        url: str = request.get("url") or ""
        method = (request.get("method") or "GET").upper()
        status = response.get("status") or 0

        m = _PROJ.search(url)
        if not m or status < 200 or status >= 300:
            skipped += 1
            continue

        service = m.group(1)
        entity, is_action = _entity_or_function(unquote(m.group(2)))
        if entity in ("$metadata", "$batch"):
            skipped += 1
            continue

        key = f"{service}::{entity}::{method}"
        group = groups.setdefault(key, OperationGroup(service=service, entity_or_function=entity, method=method, is_action=is_action))
        group.call_count += 1

        q = url.find("?")
        if q != -1:
            params: dict[str, str] = {}
            for k, v in parse_qsl(url[q + 1:], keep_blank_values=True):
                params.setdefault(k, v)  # URLSearchParams.get returns the first value
            if params.get("$select"):
                _add_unique(group.select_fields, [s.strip() for s in params["$select"].split(",")])
            if params.get("$filter"):
                _add_unique(group.filter_patterns, [anonymise_filter(unquote(params["$filter"]))])
            if params.get("$expand"):
                _add_unique(group.expand, [s.strip() for s in params["$expand"].split(",")])
            if params.get("$orderby"):
                _add_unique(group.orderby, [params["$orderby"]])
            if params.get("$top"):
                group.top = _parse_int(params["$top"])

        post_text = (request.get("postData") or {}).get("text")
        if post_text:
            body = _safe_json(post_text)
            if isinstance(body, dict):
                _add_unique(group.request_body_keys, list(body.keys()))
            elif isinstance(body, list):
                _add_unique(group.request_body_keys, [str(i) for i in range(len(body))])

        resp_text = (response.get("content") or {}).get("text")
        if group.response_sample is None and resp_text:
            body = _safe_json(resp_text)
            if body is not None:
                group.response_sample = _flatten_sample(body)

    return ParsedHar(total_entries=len(entries), filtered_count=len(groups), skipped_count=skipped, groups=list(groups.values()))


def summarise_har(parsed: ParsedHar) -> str:
    by_service: dict[str, list[OperationGroup]] = {}
    for g in parsed.groups:
        by_service.setdefault(g.service, []).append(g)

    lines = [
        f"HAR file contained {parsed.total_entries} total requests.",
        f"Found {len(parsed.groups)} distinct IFS API operation(s) across {len(by_service)} projection service(s). "
        f"Skipped {parsed.skipped_count} non-IFS or failed requests.",
        "",
    ]
    for service, groups in by_service.items():
        lines.append(f"### {service}.svc")
        for g in groups:
            tag = " [action]" if g.is_action else ""
            plural = "s" if g.call_count > 1 else ""
            lines.append(f"- **{g.method} {g.entity_or_function}**{tag} ({g.call_count} call{plural})")
            if g.select_fields:
                lines.append(f"  - Fields: {', '.join(g.select_fields)}")
            for p in g.filter_patterns:
                lines.append(f"  - Filter: `{p}`")
            if g.request_body_keys:
                lines.append(f"  - Body keys: {', '.join(g.request_body_keys)}")
        lines.append("")
    return "\n".join(lines)
