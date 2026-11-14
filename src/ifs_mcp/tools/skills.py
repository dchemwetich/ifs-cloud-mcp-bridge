"""save_skill, import_skill, parse_har_file and read_openapi_file."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx

from ..parsers.har import parse_har, summarise_har
from ..parsers.openapi import parse_openapi, summarise_openapi
from ..resources import read_raw, skills_dir
from ..util import dumps_compact, json_result, text_result

FETCH_TIMEOUT_S = 15.0
MAX_REDIRECTS = 3


def _compact_error(message: str) -> dict[str, Any]:
    return text_result(dumps_compact({"error": message}), is_error=True)


def _heading(content: str, fallback: str) -> str:
    line = next((ln for ln in content.split("\n") if ln.startswith("# ")), None)
    return re.sub(r"^#\s+", "", line).strip() if line is not None else fallback


def _dest_path(filename: str) -> tuple[Path | None, dict[str, Any] | None]:
    """Resolve filename inside the skills folder, refusing anything that escapes it."""
    folder = skills_dir()
    if not folder.exists():
        return None, _compact_error(f"Resources directory not found: {folder}")
    # abspath (not resolve) normalises ".." the way Node's path.resolve does, without expanding short names.
    dest = Path(os.path.abspath(folder / filename))
    if Path(os.path.abspath(folder)) not in dest.parents:
        return None, _compact_error("Invalid filename: must not contain path traversal sequences")
    return dest, None


# --- save_skill --------------------------------------------------------------

SAVE_DEFINITION = {
    "name": "save_skill",
    "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
    "description": (
        "Save an IFS resource guide (skill) to the skills library. "
        "For new skills, writes immediately. For existing skills, writes the update and returns a summary of what changed. "
        "Call this after drafting a skill with the ifs-skill-authoring guide (or the build_ifs_skill_from_* prompts), and only after the user has confirmed the projection and filename."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename for the skill. Must end in .md and follow the naming convention: ifs-[module]-[area].md, e.g. 'ifs-procurement-purchase-orders.md', 'ifs-sales-customer-orders.md'.",
            },
            "content": {"type": "string", "description": "Full markdown content of the skill guide."},
        },
        "required": ["filename", "content"],
    },
}


def _sections(content: str) -> list[str]:
    return [re.sub(r"^##\s+", "", ln).strip() for ln in content.split("\n") if ln.startswith("## ")]


def _fields(content: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in re.finditer(r"`([A-Z][A-Za-z0-9_]+)`", content):
        seen.setdefault(m.group(1))
    return list(seen)


def _count_examples(content: str) -> int:
    return sum(1 for ln in content.split("\n") if re.match(r"^(GET\s+)?/main/ifsapplications", ln.strip()))


def change_summary(old: str, new: str) -> str:
    old_s, new_s = _sections(old), _sections(new)
    old_f, new_f = _fields(old), _fields(new)
    delta = _count_examples(new) - _count_examples(old)
    lines = []
    added_s = [s for s in new_s if s not in old_s]
    removed_s = [s for s in old_s if s not in new_s]
    added_f = [f for f in new_f if f not in old_f]
    removed_f = [f for f in old_f if f not in new_f]
    if added_s:
        lines.append(f"+ Sections added: {', '.join(added_s)}")
    if removed_s:
        lines.append(f"- Sections removed: {', '.join(removed_s)}")
    if added_f:
        lines.append(f"+ Fields added: {', '.join(added_f)}")
    if removed_f:
        lines.append(f"- Fields removed: {', '.join(removed_f)}")
    if delta > 0:
        lines.append(f"+ {delta} new example(s) added")
    if delta < 0:
        lines.append(f"- {abs(delta)} example(s) removed")
    if not lines:
        size = len(new) - len(old)
        if size == 0:
            return "No changes detected."
        lines.append(f"Content expanded by ~{size} characters" if size > 0 else f"Content reduced by ~{abs(size)} characters")
    return "\n".join(lines)


async def save_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    filename, content = args.get("filename"), args.get("content")
    if not filename or not content:
        return _compact_error("filename and content are required")
    if not filename.endswith(".md"):
        filename += ".md"
    dest, err = _dest_path(filename)
    if err:
        return err
    is_update = dest.exists()
    changes = change_summary(read_raw(dest), content) if is_update else None
    dest.write_text(content, encoding="utf-8", newline="")
    result: dict[str, Any] = {
        "success": True,
        "action": "updated" if is_update else "created",
        "skill": _heading(content, filename),
        "filename": filename,
        "path": str(dest),
        "note": "The skill is available immediately - no restart needed.",
    }
    if changes:
        result["changes"] = changes
    return json_result(result)


# --- import_skill ------------------------------------------------------------

IMPORT_DEFINITION = {
    "name": "import_skill",
    "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    "description": (
        "Import an IFS resource guide (skill) from an HTTPS URL or local file path and make it available immediately. "
        "Useful for sharing skills between users - share the .md file and others can import it with this tool. "
        "The skill is available immediately after import - no restart needed."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": (
                    "HTTPS URL or absolute local file path to the skill .md file. "
                    "GitHub raw URLs work well: https://raw.githubusercontent.com/user/repo/main/skills/my-skill.md"
                ),
            },
            "filename": {
                "type": "string",
                "description": (
                    "Optional. Filename to save as (e.g. 'ifs-purchase-orders.md'). "
                    "Defaults to the last segment of the source URL or path. Must end in .md"
                ),
            },
        },
        "required": ["source"],
    },
}


async def fetch_url(url: str, redirects_left: int = MAX_REDIRECTS) -> str:
    """GET an https:// URL, following at most MAX_REDIRECTS redirects, each re-checked for https."""
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
        while True:
            if not url.startswith("https://"):
                raise ValueError("Only HTTPS URLs are allowed for remote skill import")
            resp = await client.get(url)
            if resp.status_code in (301, 302, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise ValueError("Redirect with no Location header")
                if redirects_left <= 0:
                    raise ValueError("Too many redirects")
                redirects_left -= 1
                url = location
                continue
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code} fetching {url}")
            return resp.content.decode("utf-8", errors="replace")


async def import_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    source, filename = args.get("source"), args.get("filename")
    if not source:
        return _compact_error("source is required")
    if not filename:
        segment = re.split(r"[/\\]", source)[-1] or "imported-skill.md"
        filename = segment if "." in segment else segment + ".md"
    if not filename.endswith(".md"):
        filename += ".md"

    try:
        if source.startswith(("http://", "https://")):
            content = await fetch_url(source)
        else:
            content = read_raw(source)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        return _compact_error(f"Could not read source: {exc}")

    if not content.strip().startswith("#"):
        return _compact_error("Source does not appear to be a valid skill file (must start with a # heading)")

    dest, err = _dest_path(filename)
    if err:
        return err
    dest.write_text(content, encoding="utf-8", newline="")
    return json_result({
        "success": True,
        "skill": _heading(content, filename),
        "saved_as": filename,
        "path": str(dest),
        "note": "The skill is available immediately - no restart needed.",
    })


# --- parse_har_file / read_openapi_file -----------------------------------------

HAR_DEFINITION = {
    "name": "parse_har_file",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    "description": (
        "Read and summarise a browser HAR file for skill authoring. "
        "Returns a structured summary of the IFS API calls found in the recording."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to the .har file exported from browser DevTools."}},
        "required": ["path"],
    },
}


async def har_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    try:
        return text_result(summarise_har(parse_har(args.get("path"))))
    except Exception as exc:
        return text_result(f"Failed to parse HAR file: {exc}", is_error=True)


OPENAPI_DEFINITION = {
    "name": "read_openapi_file",
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    "description": (
        "Read and summarise a downloaded OpenAPI/Swagger JSON file for skill authoring. "
        "Returns a structured summary of the entity sets, methods, and properties found in the spec."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to the downloaded OpenAPI/Swagger JSON file."}},
        "required": ["path"],
    },
}


async def openapi_handler(args: dict[str, Any], _oauth: Any = None) -> dict[str, Any]:
    try:
        return text_result(summarise_openapi(parse_openapi(args.get("path"))))
    except Exception as exc:
        return text_result(f"Failed to read OpenAPI file: {exc}", is_error=True)


SAVE_SKILL = (SAVE_DEFINITION, save_handler)
IMPORT_SKILL = (IMPORT_DEFINITION, import_handler)
PARSE_HAR_FILE = (HAR_DEFINITION, har_handler)
READ_OPENAPI_FILE = (OPENAPI_DEFINITION, openapi_handler)
