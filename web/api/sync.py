"""Vercel Python function: POST / DELETE /api/sync (hosted store).

POST: `Authorization: Bearer <sync key>` + a normalized shared-model body
({"source", "courses", "items"} - /api/normalize's output) -> strict
validation (hub.hosted.parse_sync) -> upsert into this student's rows.
DELETE: same bearer, wipes every row that student has.

Answers 503 until DATABASE_URL is set (the Neon store isn't provisioned
yet), so this is safe to deploy dark. hub/ gets here the same way as for
feed.py - see its docstring.
"""
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import db, hosted  # noqa: E402


class handler(hosted.Glue, BaseHTTPRequestHandler):
    def _student(self):
        key = hosted.bearer_key(self.headers)
        return hosted.student_id(key) if hosted.valid_key(key) else None

    def do_POST(self):
        if not db.hosted_url():
            return self._json(hosted.UNCONFIGURED, 503)
        student = self._student()
        if not student:
            return self._json({"error": "unauthorized"}, 401)
        body = self._read_json(hosted.MAX_BODY)
        if body is None:
            return
        try:
            courses, items = hosted.parse_sync(body)
        except ValueError:
            return self._json({"error": "body doesn't match the shared model"}, 400)
        try:
            store = db.connect_hosted(student)
            try:
                db.save(store, courses, items)
            finally:
                store.close()
        except Exception:  # generic on purpose - a driver error can quote the DSN
            return self._json({"error": "storage unavailable"}, 502)
        self._json({"stored": True, "items": len(items)})

    def do_DELETE(self):
        if not db.hosted_url():
            return self._json(hosted.UNCONFIGURED, 503)
        if not hosted.origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            return self._json({"error": "forbidden origin"}, 403)
        student = self._student()
        if not student:
            return self._json({"error": "unauthorized"}, 401)
        try:
            store = db.connect_hosted(student)
            try:
                db.wipe(store)
            finally:
                store.close()
        except Exception:
            return self._json({"error": "storage unavailable"}, 502)
        self._json({"deleted": True})
