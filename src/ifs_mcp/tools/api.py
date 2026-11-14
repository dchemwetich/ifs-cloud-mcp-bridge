"""call_protected_api, get_api_guide and export_api_data."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode

from .. import api_client, config
from ..api_client import ALLOWED_REQUEST_HEADERS, disallowed_headers
from ..auth.oauth import OAuthManager
from ..resources import Guide, get_guides
from ..util import dumps, js_string, json_result, text_result

_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


def _bad_headers_result(bad: list[str]) -> dict[str, Any]:
    return json_result({
        "error": "disallowed_headers",
        "message": f"These headers are not allowed: {', '.join(bad)}. Only {', '.join(ALLOWED_REQUEST_HEADERS)} are permitted.",
        "disallowed": bad,
    }, is_error=True)


# --- call_protected_api ------------------------------------------------------

CALL_DEFINITION = {
    "name": "call_protected_api",
    "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    "description": (
        "Call a protected IFS Cloud API endpoint using an authenticated session. "
        "IFS Cloud projection names, endpoint paths, key fields, and OData filter syntax are non-standard and vary per customer configuration. "
        "Guessing them will produce 404 errors or silently return wrong data. "
        "You MUST call get_api_guide first to get the correct endpoint and query pattern for the workflow - do not skip this step even if you think you know the endpoint. "
        "Do NOT call $metadata, probe unknown paths, or construct endpoints from scratch. "
        "If get_api_guide returns no matching guide, follow the instruction in its result: look up the screen in the client navigator, "
        "show the user the matching projection(s), and ask for confirmation before creating a new skill (always ask which one when there are several). "
        "If the response contains error 'authentication_required', immediately call start_oauth - do not relay the error to the user or ask them to authenticate manually. "
        "Targets the active IFS environment unless 'environment' is given. "
        "If the response contains error 'no_environment_selected', do not guess - show the user the listed environments and ask which one to use, then call use_ifs_environment. "
        "Pass an If-Match header for conditional PATCH/DELETE on projections that require optimistic concurrency (check the API guide or a prior GET response's @odata.etag). "
        "Pass X-IFS-Content-Disposition to set the filename IFS uses for a file upload/download."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "environment": {
                "type": "string",
                "description": "Optional: name of the IFS environment to target for this one call, overriding the active selection. Omit to use the active environment.",
            },
            "sessionId": {"type": "string", "description": "Session ID from OAuth authentication (optional - uses saved session if not provided)"},
            "endpoint": {"type": "string", "description": "API endpoint to call (relative path)"},
            "method": {"type": "string", "description": "HTTP method (GET, POST, etc.)", "enum": _METHODS},
            "body": {"type": "object", "description": "Request body (for POST/PUT/PATCH)"},
            "headers": {
                "type": "object",
                "description": "Optional request headers. Only If-Match, If-None-Match (OData optimistic concurrency) and X-IFS-Content-Disposition (IFS's custom header for naming an uploaded/downloaded file) are allowed - any other header is rejected.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["endpoint", "method"],
    },
}

MAX_RESPONSE_SIZE = 100 * 1024


def _large_response_summary(data: Any, endpoint: str) -> dict[str, Any] | None:
    records = data.get("value") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        return None
    total = len(records)
    sample = records[0]
    fields = list(sample.keys()) if isinstance(sample, dict) else [str(i) for i in range(len(sample))] if isinstance(sample, list) else []
    return {
        "_instruction": f"The query returned {total} records which is too large to display. Present the options below to the user in a friendly, conversational way. Don't list them robotically - weave them into a natural response. Mention the record count and a couple of interesting fields from the sample record to give context.",
        "total_records": total,
        "available_fields": fields,
        "sample_record": sample,
        "options": {
            "preview": "Show a preview: re-run with $top=N (e.g., $top=10) to see the first few records.",
            "filter": f"Narrow it down: add $filter on fields like {', '.join(fields[:3])} to find specific records.",
            "select_fields": f"Slim the columns: use $select to return only the fields they care about (e.g., $select={','.join(fields[:3])}).",
            "export": f"Save it all: use export_api_data to download all {total} records as a CSV file to their Downloads folder.",
        },
        "endpoint_used": endpoint,
    }


async def call_handler(args: dict[str, Any], oauth: OAuthManager) -> dict[str, Any]:
    session_id, endpoint, method = args.get("sessionId"), args.get("endpoint"), args.get("method")
    body, environment, headers = args.get("body"), args.get("environment"), args.get("headers")

    bad = disallowed_headers(headers)
    if bad:
        return _bad_headers_result(bad)

    cfg = config.load_config()
    env_names = list(cfg["environments"])
    if not env_names and not os.environ.get("API_BASE_URL"):
        return json_result({
            "error": "no_environment_configured",
            "message": "No IFS environment is configured. Ask the user for their IFS Cloud URL, OAuth realm, and client ID, then call add_ifs_environment.",
        }, is_error=True)

    target = environment if environment is not None else cfg["activeEnv"]
    # Several environments and none selected: refuse rather than guess (avoids hitting production).
    if not target and len(env_names) > 1:
        return json_result({
            "error": "no_environment_selected",
            "message": "Multiple IFS environments exist but none is selected. Ask the user which one to use, then call use_ifs_environment.",
            "environments": env_names,
        }, is_error=True)
    if environment and environment not in cfg["environments"]:
        return json_result({
            "error": "unknown_environment",
            "message": f"Environment '{environment}' is not configured.",
            "environments": env_names,
        }, is_error=True)

    target_env = config.get_environment(target) if target else None
    if target_env and target_env.get("readOnly") and method != "GET":
        return json_result({
            "error": "read_only_environment",
            "message": f"Environment '{target}' is marked read-only; {method} is blocked. Only GET requests are allowed.",
        }, is_error=True)

    result = await api_client.call_protected_api(
        oauth, endpoint, method, session_id if session_id is not None else environment, body, headers
    )
    if not result["success"]:
        return json_result({k: result[k] for k in ("error", "status", "message", "details") if k in result},
                           is_error=True)

    response_json = dumps({"status": result["status"], "data": result["data"]})
    if len(response_json) > MAX_RESPONSE_SIZE:
        summary = _large_response_summary(result["data"], endpoint)
        if summary:
            return json_result(summary)
    return text_result(response_json)


# --- get_api_guide -----------------------------------------------------------

GUIDE_DEFINITION = {
    "name": "get_api_guide",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    "description": "Look up the skill guide for an IFS workflow before querying the API. IFS Cloud endpoint paths, projection names, key fields, and OData filter syntax are customer-specific and non-standard - they cannot be inferred from general OData or REST knowledge. Call this first with a keyword (e.g. 'customer', 'sales', 'parts') to get the correct endpoints and query patterns. Call without arguments to list all available guides. To find which projection a screen or page uses, load the 'ifs-framework-client-navigator' guide. If no guide matches, the result explains how to find the projection via the navigator and offer to build a new skill.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "guide": {
                "type": "string",
                "description": "The guide to retrieve - one or more keywords, or an exact guide name (e.g. 'ifs-common-odata-reference'). Matched case-insensitively against each guide's name, URI and description; the best match is returned. Lists all available guides if omitted.",
            },
        },
    },
}

_STOPWORDS = {"ifs", "the", "and", "for", "use", "when", "with", "from", "that", "this", "how", "what", "which", "guide", "skill"}

_NO_MATCH_INSTRUCTION = "\n".join([
    "No existing skill guide matches that request. Do NOT guess or probe IFS endpoints.",
    "Do NOT tell the user you cannot help yet - first try to find the right page through the IFS client navigator:",
    "1. If the user already named a projection (e.g. 'CustomerHandling'), skip to step 3 with that projection.",
    "2. Otherwise call get_api_guide({ guide: 'ifs-framework-client-navigator' }) and follow it, using call_protected_api to search the navigator for the screen/page name in the user's own words. Deduplicate hits by Projection.",
    "   - No hits: tell the user the screen was not found in the navigator and offer to build a skill from a HAR recording (build_ifs_skill_from_har).",
    "   - Present the hit(s) to the user as a table of Label | PageType | Projection, and ASK whether they want a skill created from the projection. If there are SEVERAL distinct hits, always ask which one to use - never pick one yourself and never create a skill without an explicit answer. If the only hit is an /Assistant (wizard), include the assistant warning from the navigator guide.",
    "3. Only after the user confirms a projection: call get_api_guide({ guide: 'ifs-skill-authoring' }), fetch /main/ifsapplications/projection/v1/{Projection}.svc/$openapi?V2 with call_protected_api, work through it with the user as the authoring guide describes, and save it with save_skill (this is what the build_ifs_skill_from_projection prompt does).",
    "4. When the skill is saved, continue with the user's original request using the new guide.",
])


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3 and t not in _STOPWORDS]


def _slug(uri: str) -> str:
    return re.sub(r"/guide$", "", re.sub(r"^ifs://", "", uri))


def score_guides(guides: list[Guide], query: str) -> list[tuple[Guide, int]]:
    """Exact slug/URI/name match wins (1000); else 10 for a substring, 3 per word in slug/name, 1 per word in description."""
    needle = query.strip().lower()
    tokens = _tokenize(needle)
    scored = []
    for g in guides:
        uri = g.uri.lower()
        slug = _slug(uri)
        name = g.name.lower()
        desc = g.description.lower()
        if needle in (slug, uri, name):
            scored.append((g, 1000))
            continue
        score = 0
        if len(needle) >= 3 and (needle in slug or needle in name):
            score += 10
        for t in tokens:
            if t in slug or t in name:
                score += 3
            if t in desc:
                score += 1
        scored.append((g, score))
    return sorted([s for s in scored if s[1] > 0], key=lambda s: -s[1])


async def guide_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    guide = args.get("guide")
    guides = get_guides()
    if not guide:
        return json_result({"available_guides": [{"name": g.name, "uri": g.uri, "description": g.description} for g in guides]})

    matches = score_guides(guides, str(guide))
    if not matches:
        return json_result({
            "error": f"No guide found for '{guide}'.",
            "available_guides": [g.uri for g in guides],
            "instruction": _NO_MATCH_INSTRUCTION,
        }, is_error=True)

    best, best_score = matches[0]
    text = best.read() or "Guide content not available"
    # A close runner-up means the query was ambiguous: say so, so the model can load it too.
    others = [_slug(g.uri) for g, s in matches[1:4] if best_score < 1000 and s >= best_score / 2]
    if others:
        text += (f"\n\n---\nOther guides also matched '{guide}': {', '.join(others)}. "
                 "Call get_api_guide with one of those names if this guide does not cover the request.")
    return text_result(text)


# --- export_api_data ---------------------------------------------------------

EXPORT_DEFINITION = {
    "name": "export_api_data",
    "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    "description": "Export large API result sets to a CSV file. Fetches data in batches of 100 records using $top/$skip pagination and saves to ~/Downloads/ (or ~/.ifs-mcp/exports/ if that doesn't exist). Use this when call_protected_api returns a 'Response too large' warning. Keyed/singleton endpoints (e.g. CompanySet(Company='10')) are also supported - exported as a single row, without pagination.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "endpoint": {"type": "string", "description": "API endpoint to call (same as used with call_protected_api)"},
            "method": {"type": "string", "description": "HTTP method", "enum": _METHODS},
            "filename": {"type": "string", "description": "Output filename without extension (e.g., 'quick-reports'). Defaults to 'export'."},
            "environment": {"type": "string", "description": "Optional: name of the IFS environment to export from, overriding the active selection."},
            "sessionId": {"type": "string", "description": "Session ID (optional - uses saved session if not provided)"},
            "body": {"type": "object", "description": "Request body (for POST/PUT/PATCH)"},
            "headers": {
                "type": "object",
                "description": "Optional request headers. Only If-Match, If-None-Match, and X-IFS-Content-Disposition are allowed - any other header is rejected.",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["endpoint", "method"],
    },
}

BATCH_SIZE = 100
DELIMITER = ";"


def escape_csv_value(value: Any) -> str:
    if value is None:
        return ""
    s = js_string(value)
    if DELIMITER in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def build_csv(records: list[Any]) -> str:
    if not records:
        return ""
    headers = list(records[0].keys()) if isinstance(records[0], dict) else []
    lines = [DELIMITER.join(escape_csv_value(h) for h in headers)]
    for r in records:
        row = r if isinstance(r, dict) else {}
        lines.append(DELIMITER.join(escape_csv_value(row.get(h)) for h in headers))
    return "\n".join(lines)


def strip_pagination_params(endpoint: str) -> str:
    q = endpoint.find("?")
    if q == -1:
        return endpoint
    params = [(k, v) for k, v in parse_qsl(endpoint[q + 1:], keep_blank_values=True) if k not in ("$top", "$skip")]
    remaining = urlencode(params, quote_via=quote_plus, safe="*")
    return f"{endpoint[:q]}?{remaining}" if remaining else endpoint[:q]


def _append_param(endpoint: str, param: str) -> str:
    return f"{endpoint}&{param}" if "?" in endpoint else f"{endpoint}?{param}"


def looks_like_keyed_endpoint(endpoint: str) -> bool:
    """CompanySet(Company='10') addresses one entity: no $top/$skip (IFS rejects $skip there)."""
    return endpoint.split("?")[0].strip().endswith(")")


def safe_export_name(filename: Any) -> str:
    """Keep a model-supplied name to a plain file name inside the export folder."""
    name = re.sub(r"^\.+", "", re.sub(r"[^A-Za-z0-9._-]", "_", str(filename)))
    return name or "export"


def _export_dir() -> Path:
    downloads = Path.home() / "Downloads"
    d = downloads if downloads.exists() else Path.home() / ".ifs-mcp" / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def export_handler(args: dict[str, Any], oauth: OAuthManager) -> dict[str, Any]:
    endpoint, method = args.get("endpoint"), args.get("method")
    filename = args.get("filename") if args.get("filename") is not None else "export"
    body, headers = args.get("body"), args.get("headers")
    session_id = args.get("sessionId") if args.get("sessionId") is not None else args.get("environment")

    bad = disallowed_headers(headers)
    if bad:
        return _bad_headers_result(bad)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    output_path = _export_dir() / f"{safe_export_name(filename)}_{timestamp}.csv"
    base = strip_pagination_params(endpoint)
    records: list[Any] = []
    batches = 0

    try:
        if looks_like_keyed_endpoint(base):
            result = await api_client.call_protected_api(oauth, base, method, session_id, body, headers)
            if not result["success"]:
                return json_result({"error": "API call failed during export",
                                    "details": result.get("message") or result.get("error")}, is_error=True)
            data = result.get("data")
            # Normally a bare entity; accept {value: [...]} in case the keyed-endpoint guess was wrong.
            if isinstance(data, dict) and isinstance(data.get("value"), list):
                records = data["value"]
            else:
                records = [data] if data else []
            batches = 1
        else:
            skip = 0
            while True:
                result = await api_client.call_protected_api(
                    oauth, _append_param(base, f"$top={BATCH_SIZE}&$skip={skip}"), method, session_id, body, headers
                )
                if not result["success"]:
                    return json_result({
                        "error": "API call failed during export",
                        "batch": batches + 1,
                        "records_exported_so_far": len(records),
                        "details": result.get("message") or result.get("error"),
                    }, is_error=True)
                data = result.get("data")
                batch = data.get("value") if isinstance(data, dict) else None
                if not isinstance(batch, list) or not batch:
                    break
                records.extend(batch)
                batches += 1
                skip += BATCH_SIZE
                if len(batch) < BATCH_SIZE:
                    break

        if not records:
            return json_result({"message": "No records found to export."})

        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            fh.write("﻿" + build_csv(records))
        return json_result({
            "success": True,
            "total_records": len(records),
            "batches_fetched": batches,
            "file": str(output_path),
            "fields": list(records[0].keys()) if isinstance(records[0], dict) else [],
        })
    except Exception as exc:
        return json_result({"error": "Export failed", "message": str(exc), "records_exported_so_far": len(records)},
                           is_error=True)


CALL_PROTECTED_API = (CALL_DEFINITION, call_handler)
GET_API_GUIDE = (GUIDE_DEFINITION, guide_handler)
EXPORT_API_DATA = (EXPORT_DEFINITION, export_handler)
