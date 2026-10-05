"""Vercel Python function: GET /api/items (hosted store).

The student is `Authorization: Bearer <sync key>` (the extension) or the
httpOnly `lauds_sync` cookie /api/session sets (the dashboard). Returns that
student's upcoming items - serialized by hub.ics.to_dict, the same shape
/api/feed returns, so web/lib/hub.js reads both the same way - and courses.
503 until DATABASE_URL is set.
"""
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import db, hosted, ics  # noqa: E402
from hub.models import Item  # noqa: E402


class handler(hosted.Glue, BaseHTTPRequestHandler):
    def do_GET(self):
        if not db.hosted_url():
            return self._json(hosted.UNCONFIGURED, 503)
        key = hosted.bearer_key(self.headers) or hosted.cookie_key(self.headers)
        if not hosted.valid_key(key):
            return self._json({"error": "unauthorized"}, 401)
        try:
            store = db.connect_hosted(hosted.student_id(key))
            try:
                rows, courses = db.upcoming(store), db.courses(store)
            finally:
                store.close()
        except Exception:  # generic on purpose - a driver error can quote the DSN
            return self._json({"error": "storage unavailable"}, 502)
        now = datetime.now(timezone.utc)
        items = [Item(course=code, category=category, kind=kind, title=title,
                      due=datetime.fromisoformat(due), url=url, source=source,
                      done=None if done is None else bool(done))
                 for code, category, kind, title, due, url, done, source in rows]
        self._json({
            "items": [ics.to_dict(i, now) for i in items],
            "courses": [{"code": c, "term": t, "title": ti, "grade": g} for c, t, ti, g in courses],
        })
