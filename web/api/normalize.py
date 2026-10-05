"""Stateless Vercel function: provider capture -> shared-model rows.

The extension keeps the returned rows in its browser until a private durable
store is approved and connected. This route never claims to persist them.
"""
# ponytail: return rows to trusted extension storage until authenticated durable storage exists.
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import captures  # noqa: E402


MAX_BODY = 1_000_000


class handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log request metadata from student captures.

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"error": "expected JSON"}, 400)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json({"error": "invalid body length"}, 400)
        if not 0 < length <= MAX_BODY:
            return self._json({"error": "body exceeds the capture limit"}, 413)
        try:
            capture = json.loads(self.rfile.read(length))
            result = captures.normalize(capture)
        except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
            return self._json({"error": "invalid provider capture"}, 400)
        except Exception:
            return self._json({"error": "provider normalization unavailable"}, 502)
        self._json(result)
