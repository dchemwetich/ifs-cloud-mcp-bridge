"""Login and result pages: values are escaped, no scripts or external resources."""

import re

from ifs_mcp.ui import login_page, result_page


def _external_refs(html: str) -> list[str]:
    return [u for u in re.findall(r'(?:src|href)="([^"]+)"', html) if not u.startswith("data:")]


def test_login_page_escapes_and_links_only_to_ifs():
    url = "https://ifs.example/auth?client_id=a&state=x\"><script>"
    html = login_page(url, "<b>dev</b>", "ifs.example", read_only=True)
    assert "<script" not in html
    assert "&lt;b&gt;dev&lt;/b&gt;" in html
    assert "Read-only" in html
    assert _external_refs(html) == ["https://ifs.example/auth?client_id=a&amp;state=x&quot;&gt;&lt;script&gt;"]


def test_result_pages():
    ok = result_page(True, environment="dev")
    assert "Authentication Successful!" in ok and "<b>dev</b>" in ok
    bad = result_page(False, error="<img src=x onerror=alert(1)>")
    assert "Authentication Failed" in bad and "<img src=x" not in bad
    assert _external_refs(ok) == [] and _external_refs(bad) == []
