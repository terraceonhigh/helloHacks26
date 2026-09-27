"""Experimental UI direction: a static page + a tiny JSON API, instead of
Streamlit's server-rendered rerun-everything model (see app.py on `terrace`).
Stdlib only (http.server, json) - no new dependency, so nothing to ask the
team about per AGENTS.md.

Rows are ranked and annotated with status/urgency here (hub.logic/hub.models),
never recomputed in web/ - see web/lib/hub.js's normaliseApiItem().

Read-mostly, localhost-only demo server (POST /api/connect/* opens a
Playwright login window on THIS machine - never expose this past 127.0.0.1).
Try it:  uv run python -m hub.api
"""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from hub import canvas, db, prairielearn
from hub.logic import sort_items
from hub.models import Item, classify_urgency, status_of

UI_DIR = Path(__file__).parent.parent / "ui"

# web/'s dev server (npm run dev). Reflected back only for this exact origin,
# never "*" - the connect endpoints trigger a real browser login, so a
# wildcard would let any page on the internet read the response.
ALLOWED_ORIGIN = "http://localhost:3000"


def _item_of(row):
    code, category, kind, title, due, url, done, source = row
    return Item(course=code, category=category, kind=kind, title=title,
                due=datetime.fromisoformat(due) if due else None, url=url, source=source,
                done=bool(done) if done is not None else None)


def _row_to_dict(row, now):
    code, category, kind, title, due, url, done, source = row
    item = _item_of(row)
    return {
        "course": code, "category": category, "kind": kind, "title": title, "due": due, "url": url,
        "source": source,
        "done": bool(done) if done is not None else None,
        "status": status_of(item, now),
        "urgency": classify_urgency(title, item.due, now),
    }


def _upcoming(conn):
    """Ranked rows, never-done (matches app.py's df2e178 rule - hide_overdue
    is a client-side toggle in web/, applied against each row's `status`)."""
    now = datetime.now(timezone.utc)
    rows = [r for r in db.upcoming(conn) if status_of(_item_of(r), now) != "done"]
    rows = sort_items(rows, now)
    return [_row_to_dict(r, now) for r in rows]


def _textbooks(conn):
    return [{"course": code, "title": title, "isbn": isbn, "required": bool(required), "price": price, "url": url}
            for code, title, isbn, required, price, url in db.textbooks(conn)]


def _announcements(conn):
    """Undated items (announcements, and anything else without a real
    deadline) - already most-recent-first from db.undated(). No urgency
    ranking here, unlike _upcoming(): sort_items() needs a due date to rank
    by, and these don't have one."""
    now = datetime.now(timezone.utc)
    return [_row_to_dict(r, now) for r in db.undated(conn)]


class Handler(BaseHTTPRequestHandler):
    def _cors_origin(self):
        origin = self.headers.get("Origin")
        return origin if origin == ALLOWED_ORIGIN else None

    def _cors_headers(self):
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """CORS preflight for the connect POSTs (and belt-and-suspenders for
        the GETs) - web/ runs on a different origin (:3000 vs :8000/:8099)."""
        self.send_response(204)
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/upcoming":
            self._json(_upcoming(db.connect()))
        elif path == "/api/announcements":
            self._json(_announcements(db.connect()))
        elif path == "/api/courses":
            conn = db.connect()
            self._json([{"code": c, "term": t, "title": ti, "grade": g} for c, t, ti, g in db.courses(conn)])
        elif path == "/api/textbooks":
            self._json(_textbooks(db.connect()))
        elif path in ("/", "/index.html"):
            self._serve_file(UI_DIR / "index.html", "text/html")
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/connect/canvas":
            self._connect(canvas.fetch)
        elif path == "/api/connect/prairielearn":
            self._connect(prairielearn.fetch)
        else:
            self._json({"error": "not found"}, status=404)

    def _connect(self, fetch_fn):
        """Opens a browser window for the student to sign in themselves
        (same flow as app.py's Connect buttons), then saves and returns
        counts. web/ refetches /api/upcoming afterward for the ranked rows."""
        try:
            courses, items = fetch_fn()
        except Exception as e:  # ponytail: one broad catch at the API boundary - a failed
            # login/scrape shouldn't take the server down; the specific adapters already
            # handle their own retries/backoff (hub/site.py). Surface the message as-is.
            return self._json({"ok": False, "error": str(e)}, status=502)
        db.save(db.connect(), courses, items)
        self._json({"ok": True, "courses": len(courses), "items": len(items)})

    def _serve_file(self, path, content_type):
        if not path.exists():
            return self._json({"error": "not found"}, status=404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # ponytail: quiet by default; flip this back on if you need to debug requests


def serve(port=8000):
    # 127.0.0.1, not "localhost": binds the literal loopback address, not
    # whatever a machine's /etc/hosts or IPv6 resolution makes "localhost" mean.
    print(f"http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
