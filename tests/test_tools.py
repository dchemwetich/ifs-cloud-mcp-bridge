"""Rules 10-14 and the parsers: export, import, guides, HAR, OpenAPI."""

import json

import anyio
import httpx
import pytest

from ifs_mcp.parsers.har import anonymise_filter, parse_har, summarise_har
from ifs_mcp.parsers.openapi import parse_openapi
from ifs_mcp.resources import get_guides, parse_metadata
from ifs_mcp.tools import api, skills
from ifs_mcp.util import js_string

# --- export (rule 11) ----------------------------------------------------------


def test_csv_values_follow_javascript_string_rules():
    assert [js_string(v) for v in (True, 1.0, 1.5, [1, None, "a"], {"a": 1})] == ["true", "1", "1.5", "1,,a", "[object Object]"]
    assert api.escape_csv_value(None) == ""
    assert api.escape_csv_value('a;"b"') == '"a;""b"""'
    assert api.build_csv([{"A": 1, "B": "x\ny"}, {"A": None}]) == 'A;B\n1;"x\ny"\n;'


def test_pagination_and_keyed_endpoints():
    assert api.strip_pagination_params("/S?$top=5&$filter=a eq 'b'&$skip=10") == "/S?%24filter=a+eq+%27b%27"
    assert api.strip_pagination_params("/S?$top=5") == "/S"
    assert api.looks_like_keyed_endpoint("/CompanySet(Company='10')?$select=A")
    assert not api.looks_like_keyed_endpoint("/CompanySet?$filter=(a)")


def test_export_dir_env_overrides_downloads(home, monkeypatch, tmp_path):
    (home / "Downloads").mkdir(exist_ok=True)
    monkeypatch.delenv("EXPORT_DIR", raising=False)
    assert api._export_dir() == home / "Downloads"
    target = tmp_path / "exports" / "nested"
    monkeypatch.setenv("EXPORT_DIR", str(target))
    assert api._export_dir() == target and target.is_dir()  # created on demand


def test_export_name_cannot_leave_folder():
    assert api.safe_export_name("../../etc/passwd") == "_.._etc_passwd"
    assert api.safe_export_name("...") == "export"
    assert api.safe_export_name("my report") == "my_report"


# --- import (rule 12) ----------------------------------------------------------


def test_import_https_only_and_redirect_limit(monkeypatch):
    real = httpx.AsyncClient
    hops = {"n": 0}

    def handler(request):
        hops["n"] += 1
        if str(request.url) == "https://a.example/loop":
            return httpx.Response(302, headers={"location": "https://a.example/loop"})
        if str(request.url) == "https://a.example/downgrade":
            return httpx.Response(301, headers={"location": "http://a.example/x"})
        return httpx.Response(200, text="# ok")

    monkeypatch.setattr(skills.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ValueError, match="Too many redirects"):
        anyio.run(skills.fetch_url, "https://a.example/loop")
    assert hops["n"] == 4  # first request + 3 redirects
    with pytest.raises(ValueError, match="Only HTTPS"):
        anyio.run(skills.fetch_url, "https://a.example/downgrade")
    assert anyio.run(skills.fetch_url, "https://a.example/fine") == "# ok"


def test_save_skill_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    out = anyio.run(lambda: skills.save_handler({"filename": "../x.md", "content": "# x"}))
    assert out["isError"] and not (tmp_path.parent / "x.md").exists()
    out = anyio.run(lambda: skills.save_handler({"filename": "ok", "content": "# Ok"}))
    assert json.loads(out["content"][0]["text"])["action"] == "created"


# --- guides (rule 13) ----------------------------------------------------------


def test_skills_dir_overrides_bundled_and_metadata(tmp_path, monkeypatch):
    (tmp_path / "ifs-common-odata-reference.md").write_text("# Mine\n\n**Bold** `desc`\n", encoding="utf-8")
    (tmp_path / "ifs-custom.md").write_text("no heading\nsecond", encoding="utf-8")
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    guides = {g.uri: g for g in get_guides()}
    assert guides["ifs://ifs-common-odata-reference/guide"].name == "Mine"
    assert guides["ifs://ifs-common-odata-reference/guide"].description == "Bold desc"
    assert guides["ifs://ifs-custom/guide"].name == "ifs-custom"
    assert "ifs://ifs-framework-client-navigator/guide" in guides
    assert parse_metadata("# T\r\n\r\nLine\r\n", "a.md") == ("T", "Line", "a")


def test_guide_scoring():
    guides = get_guides()
    top = api.score_guides(guides, "ifs-framework-client-navigator")[0]
    assert top[1] == 1000
    assert api.score_guides(guides, "zzz qqq") == []


# --- parsers -------------------------------------------------------------------


def test_anonymise_filter():
    f = "OrderNo eq 'C1' and State eq 'IfsApp.X.Y' and contains(Name, 'Ac') and D eq 2026-01-02 and A gt 5"
    assert anonymise_filter(f) == (
        "OrderNo eq '{value}' and State eq 'IfsApp.X.Y' and contains(Name, '{value}') and D eq {date} and A gt {number}"
    )


def test_har_groups_and_skips(tmp_path):
    har = {"log": {"entries": [
        {"request": {"method": "GET", "url": "https://x/main/ifsapplications/projection/v1/A.svc/BSet?$select=X,Y"},
         "response": {"status": 200, "content": {"text": '{"value":[{"X":1}]}'}}},
        {"request": {"method": "GET", "url": "https://x/main/ifsapplications/projection/v1/A.svc/BSet?$select=Y,Z"},
         "response": {"status": 200}},
        {"request": {"method": "POST", "url": "https://x/projection/v1/A.svc/BSet(K='1')/IfsApp.A.B_Do",
                     "postData": {"text": '{"P":1}'}}, "response": {"status": 204}},
        {"request": {"url": "https://x/projection/v1/A.svc/$metadata"}, "response": {"status": 200}},
        {"request": {"url": "https://x/other"}, "response": {"status": 200}},
    ]}}
    p = tmp_path / "r.har"
    p.write_text(json.dumps(har))
    parsed = parse_har(str(p))
    assert (parsed.total_entries, parsed.skipped_count, len(parsed.groups)) == (5, 2, 2)
    get = parsed.groups[0]
    assert get.select_fields == ["X", "Y", "Z"] and get.call_count == 2 and get.response_sample == {"X": "number"}
    assert parsed.groups[1].is_action and parsed.groups[1].request_body_keys == ["P"]
    assert "- **POST B_Do** [action] (1 call)" in summarise_har(parsed)


def test_openapi_entity_sets_and_actions(tmp_path):
    spec = {"info": {"title": "S"}, "servers": [{"url": "/base"}], "paths": {
        "/ASet": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"properties": {
            "value": {"items": {"$ref": "#/components/schemas/A"}}}}}}}}}},
        "/ASet('{Id}')": {"patch": {}},
        "/Do_It(X=1)": {"post": {}},
    }, "components": {"schemas": {"A": {"required": ["Id"], "properties": {"Id": {"type": "string"},
                                                                            "E": {"enum": ["x", False]}}}}}}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(spec))
    parsed = parse_openapi(str(p))
    es = parsed.entity_sets[0]
    assert (parsed.base_path, es.name, es.entity_type_name, es.key_property) == ("/base", "ASet", "A", "Id")
    assert es.collection_methods == ["GET"] and es.single_methods == ["PATCH"]
    assert es.properties[1].enum_values == ["x", "false"]
    assert [(a.name, a.method) for a in parsed.actions] == [("Do_It", "POST")]
