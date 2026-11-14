"""Summarise an IFS projection OpenAPI / Swagger spec for skill authoring."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_HTTP_METHODS = ("get", "post", "patch", "put", "delete")


@dataclass
class PropertyInfo:
    name: str
    type: str
    nullable: Any
    read_only: bool = False
    enum_values: list[str] | None = None
    max_length: Any = None


@dataclass
class EntitySet:
    name: str
    entity_type_name: str
    key_property: str | None
    collection_methods: list[str]
    single_methods: list[str]
    properties: list[PropertyInfo]
    required_properties: list[str]


@dataclass
class Action:
    name: str
    method: str
    path_pattern: str


@dataclass
class ParsedOpenApi:
    service_name: str
    base_path: str
    entity_sets: list[EntitySet]
    actions: list[Action]
    total_paths: int


@dataclass
class _Entry:
    collection_methods: list[str] = field(default_factory=list)
    single_methods: list[str] = field(default_factory=list)
    key_property: str | None = None
    schema_ref: str | None = None


def _get(obj: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _key_property(path_pattern: str) -> str | None:
    m = re.search(r"\('\{(\w+)\}'\)", path_pattern)
    return m.group(1) if m else None


def _definitions(spec: dict[str, Any]) -> dict[str, Any]:
    defs = spec.get("definitions")
    if defs is None:
        defs = _get(spec, "components", "schemas")
    return defs if isinstance(defs, dict) else {}


def _ref_name(ref: str) -> str:
    return re.sub(r"^#/components/schemas/", "", re.sub(r"^#/definitions/", "", ref))


def _resolve_props(ref: str | None, spec: dict[str, Any]) -> dict[str, Any]:
    if not ref:
        return {}
    props = _get(_definitions(spec).get(_ref_name(ref)), "properties")
    return props if isinstance(props, dict) else {}


def _resolve_required(ref: str | None, spec: dict[str, Any]) -> list[str]:
    if not ref:
        return []
    req = _get(_definitions(spec).get(_ref_name(ref)), "required")
    return req if isinstance(req, list) else []


def _schema_ref(operation: Any) -> str | None:
    params = _get(operation, "parameters")
    if isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and p.get("in") == "body" and _get(p, "schema", "$ref"):
                return p["schema"]["$ref"]
    content = _get(operation, "requestBody", "content")
    if isinstance(content, dict):
        for ct in content.values():
            ref = _get(ct, "schema", "$ref")
            if ref:
                return ref
    resp = _get(operation, "responses", "200")
    ref = _get(resp, "schema", "$ref")
    if ref is None:
        ref = _get(resp, "content", "application/json", "schema", "properties", "value", "items", "$ref")
    return ref


def _js_string(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    return str(v)


def _property(name: str, d: Any) -> PropertyInfo:
    d = d if isinstance(d, dict) else {}
    ptype = d.get("type") if d.get("type") is not None else ("object" if d.get("$ref") else "string")
    nullable = d.get("x-nullable") if d.get("x-nullable") is not None else d.get("nullable", False)
    if nullable is None:
        nullable = False
    info = PropertyInfo(name=name, type=ptype, nullable=nullable)
    if d.get("readOnly"):
        info.read_only = True
    if d.get("maxLength"):
        info.max_length = d["maxLength"]
    if isinstance(d.get("enum"), list) and d["enum"]:
        info.enum_values = [_js_string(v) for v in d["enum"]]
    return info


def _entity_set_name(raw_path: str) -> str | None:
    parts = raw_path.split("/")
    segment = parts[1] if len(parts) > 1 else ""
    if not segment or segment.startswith("$") or segment.startswith("IfsApp"):
        return None
    return segment.split("(")[0]


def _action_name(raw_path: str) -> str:
    m = re.search(r"IfsApp\.[^(]+\.(\w+)", raw_path)
    if m:
        return m.group(1)
    parts = raw_path.split("/")
    if len(parts) > 1:
        return parts[1].split("(")[0]
    return raw_path


def parse_openapi(file_path: str) -> ParsedOpenApi:
    with open(file_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    if not isinstance(spec, dict):
        raise ValueError("OpenAPI file is not a JSON object")

    service_name = _get(spec, "info", "title") or "UnknownService"
    base_path = spec.get("basePath") or ""
    servers = spec.get("servers")
    if not base_path and isinstance(servers, list) and servers:
        base_path = _get(servers[0], "url") or ""

    paths = spec.get("paths") or {}
    entities: dict[str, _Entry] = {}
    actions: list[Action] = []

    for raw_path, item in paths.items():
        if not isinstance(item, dict):
            continue
        methods = [k for k in item if k in _HTTP_METHODS]

        if "IfsApp." in raw_path or re.search(r"\w+_\w+\(", raw_path):
            name = _action_name(raw_path)
            actions.extend(Action(name=name, method=m.upper(), path_pattern=raw_path) for m in methods)
            continue

        es_name = _entity_set_name(raw_path)
        if not es_name:
            continue
        entry = entities.setdefault(es_name, _Entry())
        singleton = "(" in raw_path
        for m in methods:
            upper = m.upper()
            if singleton:
                if upper not in entry.single_methods:
                    entry.single_methods.append(upper)
                if not entry.key_property:
                    entry.key_property = _key_property(raw_path)
            elif upper not in entry.collection_methods:
                entry.collection_methods.append(upper)
            if not entry.schema_ref:
                entry.schema_ref = _schema_ref(item[m])

    entity_sets = []
    for name, entry in entities.items():
        entity_sets.append(
            EntitySet(
                name=name,
                entity_type_name=name[:-3] if name.endswith("Set") else name,
                key_property=entry.key_property,
                collection_methods=entry.collection_methods,
                single_methods=entry.single_methods,
                properties=[_property(p, d) for p, d in _resolve_props(entry.schema_ref, spec).items()],
                required_properties=_resolve_required(entry.schema_ref, spec),
            )
        )

    return ParsedOpenApi(service_name=service_name, base_path=base_path, entity_sets=entity_sets,
                         actions=actions, total_paths=len(paths))


def summarise_openapi(parsed: ParsedOpenApi) -> str:
    lines = [
        f"OpenAPI spec for **{parsed.service_name}**",
        f"Base path: `{parsed.base_path}`",
        f"Total paths in spec: {parsed.total_paths}",
        "",
        f"Found **{len(parsed.entity_sets)}** entity set(s) and **{len(parsed.actions)}** action(s).",
        "",
    ]
    for es in parsed.entity_sets:
        ops = [f"{m} (collection)" for m in es.collection_methods] + [f"{m} (single)" for m in es.single_methods]
        lines.append(f"### {es.name}")
        lines.append(f"- Entity type: `{es.entity_type_name}`")
        if es.key_property:
            lines.append(f"- Key property: `{es.key_property}`")
        lines.append(f"- Operations: {', '.join(ops)}")
        lines.append(f"- Properties: {len(es.properties)} total, {len(es.required_properties)} required")
        if es.required_properties:
            lines.append(f"- Required: {', '.join(str(r) for r in es.required_properties)}")
        enums = [p for p in es.properties if p.enum_values]
        if enums:
            lines.append(f"- Enum fields: {', '.join(p.name for p in enums)}")
        lines.append("")
    if parsed.actions:
        lines.append("### Actions / Functions")
        for a in parsed.actions:
            lines.append(f"- **{a.method} {a.name}** - `{a.path_pattern}`")
        lines.append("")
    return "\n".join(lines)
