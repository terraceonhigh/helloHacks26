"""Vercel Python serverless function: /api/feed (#47).

POST {url} connects (sets an httpOnly cookie only on success), GET
refreshes from that cookie (404 if none), DELETE disconnects. The
behaviour itself is hub/ics.py's feed_request(), shared with hub/api.py.

The hosted site's counterpart to hub/api.py's /api/feed - same job (a
student pastes their Canvas calendar-feed URL, this fetches and parses it
server-side, since Canvas sends no CORS headers), different runtime.
Reuses hub/ics.py's fetch_untrusted()/to_dict() rather than reimplementing
the host allowlist, size/time limits or item parsing here (rule 1: one
parser, not two) - this file is only the HTTP glue Vercel's Python runtime
expects.

Vercel's Root Directory is `web/`, so hub/ (one level up, at the actual repo
root) is outside it by default and can't just be imported - `includeFiles:
"../hub/**"` in vercel.json looked like the fix, but Vercel rejects any
`includeFiles` path that escapes the Root Directory ("invalid file
descriptor path" at deploy time, not build time, so it looks fine right up
until it ships). Instead, the CI deploy step (.github/workflows/ci.yml)
copies hub/ to web/hub/ - inside the Root
Directory, no special Vercel setting needed - before `vercel build` runs.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import ics  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, status, payload=None, set_cookie=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Personal data: never cache, anywhere.
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _same_origin(self):
        """Hard-reject a cross-origin POST/DELETE before it runs. The
        SameSite=Strict cookie already keeps other sites from using a
        connected feed; this also stops them making a visitor's browser
        connect one or disconnect it. No Origin header at all (curl, a
        non-browser client) is let through, same as hub/api.py - a browser
        always sends one on these methods."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        hosts = {self.headers.get("Host"), self.headers.get("X-Forwarded-Host")} - {None}
        if urlparse(origin).netloc in hosts:
            return True
        self._send(403, {"error": "forbidden origin"})
        return False

    def _read_json_body(self):
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type != "application/json":
            raise ValueError("expected Content-Type: application/json")
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("bad Content-Length")
        try:
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("malformed JSON body")
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object body")
        return body

    def do_GET(self):
        self._send(*ics.feed_request("GET", self.headers.get("Cookie")))

    def do_POST(self):
        if not self._same_origin():
            return
        try:
            body = self._read_json_body()
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        self._send(*ics.feed_request("POST", None, body))

    def do_DELETE(self):
        if not self._same_origin():
            return
        self._send(*ics.feed_request("DELETE", None))

    # Never log a request: the Cookie header carries the feed URL. Vercel's
    # Python wrapper replaces log_message, so log_request/log_error are
    # silenced too.
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        pass

    def log_error(self, fmt, *args):
        pass
