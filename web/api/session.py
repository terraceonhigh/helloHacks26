"""Vercel Python function: POST /api/session (hosted store).

Trades a sync key for the httpOnly `lauds_sync` cookie, so the dashboard can
read /api/items without keeping the key in JS-readable storage. The
dashboard gets the key from a `#sync=<key>` fragment (fragments never reach
a server's logs), POSTs it here once, then drops the fragment. The key is
only format-checked - it names a student, it doesn't prove one exists.
503 until DATABASE_URL is set, so the dashboard falls back to its old data.
"""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import db, hosted  # noqa: E402


class handler(hosted.Glue, BaseHTTPRequestHandler):
    def do_POST(self):
        if not db.hosted_url():
            return self._json(hosted.UNCONFIGURED, 503)
        body = self._read_json(1024)
        if body is None:
            return
        key = body.get("key")
        if not hosted.valid_key(key):
            return self._json({"error": "invalid key"}, 400)
        self._json({"ok": True}, cookie=hosted.session_cookie(key))
