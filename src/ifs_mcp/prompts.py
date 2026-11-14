"""Prompts that start a skill-building session."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _user(text: str) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


def _projection(args: dict[str, str]) -> dict[str, Any]:
    projection, skill = args.get("projection_name"), args.get("skill_name")
    spec = f"/main/ifsapplications/projection/v1/{projection}.svc/$openapi?V2"
    return _user(
        f"I want to build an IFS resource guide for the {projection} projection. "
        f"The OpenAPI spec is at {spec}. "
        f"Save the skill as {skill}. "
        "Please load the ifs-skill-authoring guide via get_api_guide, "
        "then fetch the spec and guide me through building the skill."
    )


def _har(args: dict[str, str]) -> dict[str, Any]:
    return _user(
        "I want to build an IFS resource guide from a HAR file. "
        f"Save the skill as {args.get('skill_name')}. "
        f"Please call parse_har_file with path {args.get('har_file_path')} to analyse it, "
        "load the ifs-skill-authoring guide via get_api_guide, "
        "then guide me through building the skill."
    )


def _openapi(args: dict[str, str]) -> dict[str, Any]:
    return _user(
        "I want to build an IFS resource guide from an OpenAPI spec. "
        f"Save the skill as {args.get('skill_name')}. "
        f"Please call read_openapi_file with path {args.get('openapi_file_path')} to analyse it, "
        "load the ifs-skill-authoring guide via get_api_guide, "
        "then guide me through building the skill."
    )


PROMPTS: list[tuple[dict[str, Any], Callable[[dict[str, str]], dict[str, Any]]]] = [
    (
        {
            "name": "build_ifs_skill_from_projection",
            "description": "Build an IFS skill by fetching the OpenAPI spec live for a named projection.",
            "arguments": [
                {"name": "projection_name", "description": "IFS projection service name, e.g. 'CustomerHandling', 'TechPortalTaskExecution'.", "required": True},
                {"name": "skill_name", "description": "Filename for the skill (without .md), e.g. 'ifs-parts', 'ifs-sales-customers'.", "required": True},
            ],
        },
        _projection,
    ),
    (
        {
            "name": "build_ifs_skill_from_har",
            "description": "Build an IFS skill from a browser HAR recording.",
            "arguments": [
                {"name": "har_file_path", "description": "Absolute path to a .har file exported from browser DevTools.", "required": True},
                {"name": "skill_name", "description": "Filename for the skill (without .md), e.g. 'ifs-purchase-orders'.", "required": True},
            ],
        },
        _har,
    ),
    (
        {
            "name": "build_ifs_skill_from_openapi",
            "description": "Build an IFS skill from a downloaded OpenAPI/Swagger spec file.",
            "arguments": [
                {"name": "openapi_file_path", "description": "Absolute path to a downloaded OpenAPI/Swagger JSON file.", "required": True},
                {"name": "skill_name", "description": "Filename for the skill (without .md), e.g. 'ifs-parts'.", "required": True},
            ],
        },
        _openapi,
    ),
]
