"""Browser pages shown during login: the start page and the callback result page.

Self-contained HTML (inline CSS, logo as a data URI, no scripts or web fonts), so opening
them never contacts anything except the IFS sign-in page the user clicks through to.
Every dynamic value is HTML-escaped.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path

_LOGO = Path(__file__).resolve().parent / "logo.png"

PRODUCT = "IFS Cloud Bridge"

_CSS = """
:root{
  --bg:#f6f7f9;--card:#ffffff;--fg:#0a0a0a;--muted:#737373;--border:#ededed;--chip:#f5f5f5;
  --brand:#88c819;--brand-hover:#7ab616;--brand-fg:#0f140b;--brand-text:#4c7812;--brand-subtle:#e8f3d3;
  --danger:#b42318;--danger-subtle:#fdecea;--shadow:0 1px 2px rgba(10,10,10,.04),0 12px 32px -12px rgba(10,10,10,.12);
  --glow:rgba(136,200,25,.18);--dot:rgba(10,10,10,.06);
  color-scheme:light;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0a0a0a;--card:#111315;--fg:#fafafa;--muted:#a3a3a3;--border:#262626;--chip:#1a1c1f;
  --brand:#a3e637;--brand-hover:#b4ef55;--brand-fg:#0f140b;--brand-text:#ace949;--brand-subtle:#1d2711;
  --danger:#f97066;--danger-subtle:#2a1513;--shadow:0 1px 2px rgba(0,0,0,.4),0 16px 40px -16px rgba(0,0,0,.6);
  --glow:rgba(163,230,55,.10);--dot:rgba(255,255,255,.05);
  color-scheme:dark;
}}
*{box-sizing:border-box;margin:0;padding:0}
body{
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px 16px;
  font:15px/1.55 "Instrument Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  color:var(--fg);background:var(--bg);
  background-image:radial-gradient(600px 300px at 50% -60px,var(--glow),transparent 70%),
    radial-gradient(var(--dot) 1px,transparent 1px);
  background-size:auto,20px 20px;
}
main{width:100%;max-width:440px}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:var(--shadow);padding:32px 28px 24px}
.brand{display:flex;align-items:center;gap:10px;margin-bottom:24px}
.brand img{width:40px;height:40px;border-radius:12px;background:var(--brand-subtle);padding:4px;object-fit:contain}
.brand span{font:600 14px/1 "Space Grotesk","Instrument Sans",ui-sans-serif,system-ui,sans-serif;letter-spacing:-.01em}
.brand small{display:block;margin-top:3px;font:12px/1 ui-sans-serif,system-ui,sans-serif;color:var(--muted)}
h1{font:600 24px/1.2 "Space Grotesk","Instrument Sans",ui-sans-serif,system-ui,sans-serif;letter-spacing:-.02em;margin-bottom:6px}
.lead{color:var(--muted);margin-bottom:20px}
.env{border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:20px}
.row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 14px;font-size:14px}
.row+.row{border-top:1px solid var(--border)}
.row dt{color:var(--muted)}
.row dd{font-weight:500;text-align:right;overflow-wrap:anywhere}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;background:var(--chip)}
.badge.ok{background:var(--brand-subtle);color:var(--brand-text)}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;height:46px;border-radius:10px;
  background:var(--brand);color:var(--brand-fg);font-weight:600;font-size:15px;text-decoration:none;
  transition:background .15s,transform .15s;outline:none}
.btn:hover{background:var(--brand-hover)}
.btn:active{transform:translateY(1px)}
.btn:focus-visible{box-shadow:0 0 0 3px var(--card),0 0 0 5px var(--brand)}
.steps{display:flex;justify-content:center;gap:6px;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--muted)}
.steps b{font-weight:500;color:var(--fg)}
.foot{display:flex;align-items:center;justify-content:center;gap:6px;margin-top:20px;padding-top:16px;
  border-top:1px solid var(--border);font-size:12px;color:var(--muted);text-align:center}
.icon{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;margin-bottom:16px}
.icon.ok{background:var(--brand-subtle);color:var(--brand-text)}
.icon.err{background:var(--danger-subtle);color:var(--danger)}
.error{background:var(--danger-subtle);color:var(--danger);border-radius:10px;padding:10px 12px;margin-bottom:16px;overflow-wrap:anywhere}
.hint{font-size:14px;color:var(--muted)}
@media (prefers-reduced-motion:no-preference){.card{animation:in .35s ease-out}}
@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
"""

_LOCK = ('<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
         'aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>')
_ARROW = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
          'aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>')
_CHECK = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" '
          'aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg>')
_CROSS = ('<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" '
          'aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>')


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    try:
        return "data:image/png;base64," + base64.b64encode(_LOGO.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _page(title: str, body: str) -> str:
    logo = _logo_data_uri()
    icon = f'<link rel="icon" href="{logo}">' if logo else ""
    brand_img = f'<img src="{logo}" alt="">' if logo else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{escape(title)} · {PRODUCT}</title>
{icon}
<style>{_CSS}</style>
</head>
<body>
<main>
<div class="card">
<div class="brand">{brand_img}<div><span>{PRODUCT}</span><small>MCP server for IFS Cloud</small></div></div>
{body}
</div>
</main>
</body>
</html>
"""


def login_page(auth_url: str, environment: str, host: str, read_only: bool) -> str:
    """Start page: says where the user is about to sign in, then links to the IFS login."""
    access = ('<span class="badge">Read-only</span>' if read_only
              else '<span class="badge ok">Read &amp; write</span>')
    body = f"""<h1>Sign in to IFS Cloud</h1>
<p class="lead">Your AI agent is asking to connect to this IFS environment.</p>
<dl class="env">
  <div class="row"><dt>Environment</dt><dd>{escape(environment)}</dd></div>
  <div class="row"><dt>Instance</dt><dd class="mono">{escape(host)}</dd></div>
  <div class="row"><dt>Access</dt><dd>{access}</dd></div>
</dl>
<a class="btn" href="{escape(auth_url, quote=True)}" autofocus>Continue to IFS sign-in {_ARROW}</a>
<p class="steps"><b>Sign in on IFS</b><span>→</span><span>return here automatically</span><span>→</span><span>back to your agent</span></p>
<p class="foot">{_LOCK}<span>OAuth 2.0 + PKCE · runs on this computer · tokens are sent only to {escape(host)}</span></p>"""
    return _page("Sign in", body)


def result_page(ok: bool, environment: str | None = None, error: str | None = None) -> str:
    """Page the browser lands on after the IFS redirect."""
    if ok:
        env = f" <b>{escape(environment)}</b>" if environment else ""
        body = f"""<div class="icon ok">{_CHECK}</div>
<h1>Authentication Successful!</h1>
<p class="lead">Session saved for{env}. You can close this window and go back to your agent.</p>
<p class="foot">{_LOCK}<span>Your session is stored on this computer only.</span></p>"""
        return _page("Signed in", body)
    body = f"""<div class="icon err">{_CROSS}</div>
<h1>Authentication Failed</h1>
<p class="lead">IFS did not complete the sign-in.</p>
<p class="error mono">Error: {escape(error or "unknown error", quote=True)}</p>
<p class="hint">Close this window and ask your agent to log in again. If it keeps failing, check the IAM client's redirect URI is <span class="mono">http://localhost:3000/oauth/callback</span>.</p>"""
    return _page("Sign-in failed", body)
