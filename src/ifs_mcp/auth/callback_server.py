"""Local OAuth callback on 127.0.0.1:3000/oauth/callback, started on first login."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..ui import result_page
from . import sessions
from .oauth import OAuthManager

_started = False
_start_lock = threading.Lock()


def _make_handler(oauth: OAuthManager) -> type[BaseHTTPRequestHandler]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path != "/oauth/callback":
                self._send(404, "Not Found", "text/plain")
                return
            query = {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            if query.get("error"):
                detail = query["error"]
                if query.get("error_description"):
                    detail += f" - {query['error_description']}"
                self._send(200, result_page(False, error=detail))
                return
            try:
                key = oauth.exchange_code(query.get("code", ""), query.get("state", ""))
                data = sessions.get_token(key)
                if data:
                    sessions.save_session(key, data)
                self._send(200, result_page(True, environment=key))
            except Exception as exc:  # report any failure on the page (escaped by result_page)
                self._send(200, result_page(False, error=str(exc)))

        def _send(self, status: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # keep stdout/stderr clean for the MCP transport

    return CallbackHandler


def start_callback_server(oauth: OAuthManager) -> None:
    """Start once; if port 3000 is already taken, assume a callback server is running."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 3000), _make_handler(oauth))
        except OSError:
            return
        threading.Thread(target=server.serve_forever, name="ifs-oauth-callback", daemon=True).start()
