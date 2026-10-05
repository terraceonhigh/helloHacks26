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

from hub import canvas, db, export_ics, ics, prairielearn
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


def _all_items(conn):
    """Every item with a due date, as real Item objects - what export_ics.py
    wants (it needs .kind/.due/.url etc, not the raw row tuple). Same
    unfiltered set app.py's own "Add to my calendar" button already exports
    (no done/overdue filtering - a calendar app is a fine place to still see
    something you finished, unlike the dashboard's own upcoming list)."""
    return [_item_of(r) for r in db.upcoming(conn)]


def _announcements(conn):
    """Real announcements only - already most-recent-first from db.undated().
    No urgency ranking here, unlike _upcoming(): sort_items() needs a due date
    to rank by, and announcements don't have one.

    db.undated() is every item with no due date, not just announcements - an
    undated Canvas assignment (hub/canvas.py's to_undated_item, #43) or an
    unopened PrairieLearn assessment has no due date either, and used to leak
    into this feed looking like an announcement. Filter to kind="announcement"
    here rather than in db.undated() itself, which other undated items may
    still want to read from later.
    # ponytail: an undated task/deadline has nowhere to surface at all right
    # now (it's excluded here, and _upcoming() requires a due date) - fine
    # until something asks for an "undated tasks" list of its own.
    """
    now = datetime.now(timezone.utc)
    return [_row_to_dict(r, now) for r in db.undated(conn) if r[2] == "announcement"]


def _schedule(conn):
    """Every recurring class meeting, JSON-ready. No status/urgency here -
    those are Item concepts (due-date-relative); a meeting recurs all term,
    so "overdue"/"soon" doesn't apply to it."""
    return [
        {"course": code, "kind": kind, "days": days.split(","), "start_time": start_time,
         "end_time": end_time, "location": location, "term_start": term_start,
         "term_end": term_end, "source": source}
        for code, kind, days, start_time, end_time, location, term_start, term_end, source in db.schedule(conn)
    ]


class Handler(BaseHTTPRequestHandler):
    def _cors_origin(self):
        origin = self.headers.get("Origin")
        return origin if origin == ALLOWED_ORIGIN else None

    def _cors_headers(self):
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            # web/ sends the /api/feed cookie cross-origin (:3000 -> :8000,
            # same site), which needs credentials allowed - only ever for
            # this one exact origin.
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _json(self, payload, status=200, set_cookie=None, no_store=False):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE")
            self.send_header("Access-Control-Allow-Credentials", "true")
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
        elif path == "/api/feed":
            self._feed_reply("GET", self.headers.get("Cookie"))
        elif path == "/api/calendar/kinds":
            kinds = export_ics.known_kinds(_all_items(db.connect()))
            self._json([{"kind": k, "color": export_ics.color_for_kind(k)} for k in kinds])
        elif path == "/calendar.ics":
            self._ics(export_ics.to_ics(_all_items(db.connect())))
        elif path.startswith("/calendar/") and path.endswith(".ics"):
            kind = path[len("/calendar/"):-len(".ics")]
            self._ics(export_ics.to_ics(_all_items(db.connect()), kind=kind))
        elif path == "/api/schedule":
            self._json(_schedule(db.connect()))
        elif path in ("/", "/index.html"):
            self._serve_file(UI_DIR / "index.html", "text/html")
        else:
            self._json({"error": "not found"}, status=404)

    def _check_origin(self):
        """Hard-reject a cross-origin POST. A page on an attacker domain that
        resolves to 127.0.0.1 (DNS rebinding) could otherwise trigger a real
        Canvas login or feed fetch - _cors_headers() alone only controls
        whether the *response* is readable, it never stops the request from
        running. A request with no Origin header at all (curl, a non-browser
        client) is let through - only a browser always sends one."""
        origin = self.headers.get("Origin")
        if origin is not None and origin != ALLOWED_ORIGIN:
            self._json({"error": "forbidden origin"}, status=403)
            return False
        return True

    def do_POST(self):
        if not self._check_origin():
            return
        path = urlparse(self.path).path
        if path == "/api/connect/canvas":
            self._connect(canvas.fetch)
        elif path == "/api/connect/prairielearn":
            self._connect(prairielearn.fetch)
        elif path == "/api/connect/prairielearn_ok":
            self._connect(lambda: prairielearn.fetch("prairielearn_ok"))
        elif path == "/api/connect/prairielearn_custom":
            self._connect_prairielearn_custom()
        elif path == "/api/feed":
            self._feed()
        else:
            self._json({"error": "not found"}, status=404)

    def do_DELETE(self):
        if not self._check_origin():
            return
        if urlparse(self.path).path == "/api/feed":
            self._feed_reply("DELETE", None)
        else:
            self._json({"error": "not found"}, status=404)

    def _feed_reply(self, method, cookie_header, body=None):
        status, payload, set_cookie = ics.feed_request(method, cookie_header, body)
        self._json(payload, status=status, set_cookie=set_cookie, no_store=True)

    def _read_json_body(self):
        """Same guard on both /api/feed implementations (this one and the
        Vercel function, #47): a POST carrying a feed URL - someone's secret
        - must say so explicitly, not be guessed at from an empty/absent
        Content-Type. Also the one place a pasted PrairieLearn domain comes
        through (/api/connect/prairielearn_custom), so the same hardening
        covers both."""
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        if content_type != "application/json":
            raise ValueError("expected Content-Type: application/json")
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            raise ValueError("bad Content-Length")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("malformed JSON body")
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object body")
        return body

    def _connect_prairielearn_custom(self):
        try:
            domain = self._read_json_body().get("domain", "")
        except ValueError as e:
            return self._json({"ok": False, "error": str(e)}, status=400)
        self._connect(lambda: prairielearn.fetch(domain))

    def _feed(self):
        """POST /api/feed: {url} -> that feed's items, parsed fresh, nothing
        saved to hub.db. On success the URL goes into an httpOnly cookie
        (GET /api/feed refreshes from it, DELETE clears it). url is never
        logged - hub/ics.py's feed_request() holds the behaviour, host
        allowlist and size/time limits shared with the Vercel function
        (rule 1: one function, not two)."""
        try:
            body = self._read_json_body()
        except ValueError as e:
            return self._json({"error": str(e)}, status=400, no_store=True)
        self._feed_reply("POST", None, body)

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

    def _ics(self, body):
        """Serve a generated .ics feed (hub.export_ics). A plain GET here is
        a one-time import in any calendar app; a calendar app on THIS same
        machine can also subscribe to the URL for a live-refreshing sync -
        Google Calendar's cloud service specifically cannot, since it needs
        a publicly reachable URL and 127.0.0.1 is never that."""
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

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

    # Never log a request: /api/feed's Cookie header carries a secret.
    def log_request(self, code="-", size="-"):
        pass

    def log_error(self, fmt, *args):
        pass


def serve(port=8000):
    # 127.0.0.1, not "localhost": binds the literal loopback address, not
    # whatever a machine's /etc/hosts or IPv6 resolution makes "localhost" mean.
    print(f"http://127.0.0.1:{port}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
