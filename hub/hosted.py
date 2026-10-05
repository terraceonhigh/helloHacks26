"""Hosted sync: key -> student id, strict body validation, and the HTTP glue
web/api/sync.py, items.py and session.py share.

Auth without accounts: the *client* (browser extension) generates a random
32-byte urlsafe sync key and keeps it. The server only ever sees it in a
header or cookie, stores sha256(key) as `student`, and never logs or echoes
the key. Anyone holding the key is that student - same model as a Canvas
.ics feed URL, so it's treated as a password the same way.

Nothing here touches SQL (hub.db does) or knows a provider: the body is
already the shared model (the extension's /api/normalize output).
"""
import hashlib
import json
import re
from dataclasses import fields
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlparse

from hub.models import Course, Item

COOKIE = "lauds_sync"
COOKIE_MAX_AGE = 30 * 24 * 3600
ALLOWED_ORIGIN = "https://hello-hacks26.vercel.app"
EXTENSION_SCHEME = "chrome-extension://"
MAX_ROWS = 3000
MAX_BODY = 4_000_000  # under Vercel's 4.5 MB request cap; 3000 items fit easily
UNCONFIGURED = {"error": "hosted storage not configured"}

_KEY = re.compile(r"[A-Za-z0-9_-]{43,128}")  # 32 random bytes, base64url, no padding = 43
_SOURCE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CATEGORIES = {"task", "deadline", "material"}
_COURSE_FIELDS = {f.name for f in fields(Course)}
_ITEM_FIELDS = {f.name for f in fields(Item)}


def valid_key(key):
    return isinstance(key, str) and _KEY.fullmatch(key) is not None


def student_id(key):
    """The only form of the key the server keeps."""
    return hashlib.sha256(key.encode()).hexdigest()


def origin_ok(origin, host=None):
    """State-changing requests: our own site (same-origin, checked against
    the request's own Host so this works on any deployment - the team's,
    a fork, a preview URL - not just ALLOWED_ORIGIN), the extension's
    service worker, or no Origin at all (a non-browser client)."""
    return (not origin or origin == ALLOWED_ORIGIN or origin.startswith(EXTENSION_SCHEME)
            or (host and origin == f"https://{host}"))


def bearer_key(headers):
    auth = headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else None


def cookie_key(headers):
    try:
        morsel = SimpleCookie(headers.get("Cookie", "")).get(COOKIE)
    except CookieError:
        return None
    return morsel.value if morsel else None


def session_cookie(key):
    return (f"{COOKIE}={key}; HttpOnly; Secure; SameSite=Strict; Path=/api; "
            f"Max-Age={COOKIE_MAX_AGE}")


def _str(value, limit, required=True):
    return isinstance(value, str) and len(value) <= limit and (bool(value.strip()) or not required)


def _https(url):
    if not _str(url, 2048):
        return False
    parts = urlparse(url)
    return parts.scheme == "https" and bool(parts.netloc)


def _due(value):
    """tz-aware datetime, None, or raise ValueError."""
    if value is None:
        return None
    if not _str(value, 64):
        raise ValueError
    due = datetime.fromisoformat(value)
    if due.tzinfo is None:
        raise ValueError
    return due


def _course(row):
    if not isinstance(row, dict) or set(row) - _COURSE_FIELDS:
        raise ValueError
    grade = row.get("grade")
    if not (_str(row.get("code"), 200) and _str(row.get("title"), 500)
            and _str(row.get("section", ""), 64, False) and _str(row.get("term", ""), 64, False)
            and (grade is None or (isinstance(grade, (int, float)) and not isinstance(grade, bool)))):
        raise ValueError
    return Course(code=row["code"], section=row.get("section", ""), term=row.get("term", ""),
                  title=row["title"], grade=grade)


def _item(row, source):
    if not isinstance(row, dict) or set(row) - _ITEM_FIELDS:
        raise ValueError
    done = row.get("done")
    if not (_str(row.get("course"), 200) and row.get("category") in _CATEGORIES
            and _str(row.get("kind"), 64) and _str(row.get("title"), 500)
            and _https(row.get("url")) and row.get("source") == source
            and (done is None or isinstance(done, bool))
            and isinstance(row.get("files", []), list)):
        raise ValueError
    # ponytail: `files` is accepted but not stored - no hosted table for it
    # yet, and nothing populates it (see hub.models.Item.files).
    return Item(course=row["course"], category=row["category"], kind=row["kind"], title=row["title"],
                due=_due(row.get("due")), url=row["url"], source=source, done=done)


def parse_sync(body):
    """Normalized-model JSON -> (courses, items), or raise ValueError. All or
    nothing: one bad row rejects the whole body, so nothing half-saves."""
    if not isinstance(body, dict):
        raise ValueError
    source = body.get("source")
    courses, items = body.get("courses", []), body.get("items", [])
    if not (isinstance(source, str) and _SOURCE.fullmatch(source)
            and isinstance(courses, list) and isinstance(items, list)
            and len(courses) <= MAX_ROWS and len(items) <= MAX_ROWS):
        raise ValueError
    try:
        return [_course(c) for c in courses], [_item(i, source) for i in items]
    except (TypeError, KeyError):
        raise ValueError from None


class Glue:
    """Mixed into each route's `handler(Glue, BaseHTTPRequestHandler)` -
    feed.py's hardening, shared: JSON only, no-store, capped bodies, generic
    errors, no request logging (a key could ride along in a header).

    log_request/log_error too, not just log_message: Vercel's runtime wraps
    `handler` in a subclass whose own log_message prints to stdout and wins
    over ours in the MRO - but it doesn't define these two, so ours do."""

    def log_message(self, *args):
        pass

    def log_request(self, *args):
        pass

    def log_error(self, *args):
        pass

    def _json(self, payload, status=200, cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, limit):
        """The parsed body, or None after answering the error itself."""
        if not origin_ok(self.headers.get("Origin"), self.headers.get("Host")):
            return self._json({"error": "forbidden origin"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"error": "expected Content-Type: application/json"}, 415)
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._json({"error": "bad Content-Length"}, 400)
        if length <= 0 or length > limit:
            return self._json({"error": "body missing or too large"}, 413)
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            return self._json({"error": "expected a JSON object body"}, 400)
        return body
