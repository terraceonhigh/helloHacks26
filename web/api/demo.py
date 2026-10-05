"""Vercel Python serverless function: GET /api/demo.

The hosted site's zero-click dashboard: hub/demo.py's demo_rows() - a fake
"Demo Student" replayed through the real Canvas, calendar-feed,
PrairieLearn, Workday and key-dates adapters, then fused the way
/api/upcoming does. Stateless and input-free: no query string is read, no
cookie, no network, no database. This file is only the HTTP glue.

hub/ (with hub/demo_fixtures/) reaches web/hub/ the same way it does for
feed.py - see that file's docstring and .github/workflows/ci.yml.
"""
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub.demo import demo_rows  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _json(self, payload, status=200, cache=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            payload = demo_rows(datetime.now(timezone.utc))
        except Exception:  # ponytail: one broad catch at the boundary - the web
            # app falls back to its built-in sample rows on any non-200.
            return self._json({"error": "demo data unavailable"}, 500, cache="no-store")
        # Same for every visitor and only day-granular, so a 5-minute shared
        # cache is safe and keeps invocations down on the Hobby plan.
        self._json(payload, cache="public, max-age=300")

    # No request logging at all. Vercel's Python wrapper replaces
    # log_message, so log_request/log_error are silenced too.
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        pass

    def log_error(self, fmt, *args):
        pass
