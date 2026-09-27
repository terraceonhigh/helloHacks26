"""One iCalendar parser for any school's feed (Canvas, Moodle, ...).

Canvas and Moodle both expose a per-student .ics URL (docs/api-standards.md
"Architecture suggestion"). Feed URLs carry a secret, same as a token: never
log or commit one.

Verified against a real self-hosted Canvas (instructure/canvas-lms) feed,
found via #47: every event's URL is the *generic* course calendar page
(.../calendar?include_contexts=course_N), never the item's own page, which
broke two things - kind ("/calendar_events/" in url never matched, so
office hours and everything else came back "assignment"), and identity
(every item in a course collided on the same (source, url), breaking rule
4). UID carries the real signal instead: Canvas's own event-assignment-<id>
/ event-calendar-event-<id> format. The deep link is rebuilt from UID's id
plus the course id already sitting in that same generic URL's query string
- no extra request needed, so the no-auth "paste your feed link" flow still
needs nothing but the feed itself.

Hardened against the feed oracle + security review on #66:
- titles containing their own "[...]" were coming out blank
- an all-day date landed on the wrong calendar day in Vancouver
- the rebuilt event link didn't match Canvas's real one
- a redirect could bypass the host allowlist, and error messages echoed
  the feed URL (a secret) back to the caller
"""
import os
import re
import time
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote, urlparse
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

from hub.models import Item, category_for, classify_urgency, status_of

VANCOUVER = ZoneInfo("America/Vancouver")

# Canvas puts "[COURSE CODE]" on the end of every event/assignment summary.
# Moodle feeds don't, so course comes back "" there - fine for a first cut.
# [^\[\]]+, not a lazy .+?: a title that itself contains "[...]" (seen on
# the feed oracle) needs the LAST bracket group specifically, and a
# negated class gets that in one linear pass instead of backtracking
# through nested brackets (also avoids a ReDoS shape on adversarial input).
COURSE_SUFFIX = re.compile(r"\s*\[([^\[\]]+)\]\s*$")

# Canvas's own UID shape for a calendar-feed VEVENT.
UID_RE = re.compile(r"^event-(assignment|calendar-event)-(\d+)$")
# The course id sitting in the generic URL every feed item currently ships
# with (.../calendar?include_contexts=course_12345).
COURSE_ID_RE = re.compile(r"course_(\d+)")


def _due(dt):
    """dtstart.dt is a bare `date` for an all-day event (no time component) -
    treated as due at the end of that day, Vancouver time: UTC midnight is
    the *previous* calendar day there for most of the year, which put a
    "due today" item a day early. A naive datetime (a school's feed that
    doesn't state a timezone at all) gets the same zone attached rather
    than staying naive, which would crash anything comparing it against
    datetime.now(timezone.utc). An already-aware datetime (Canvas's own
    timed events, UTC "Z" instants) passes through unchanged."""
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=VANCOUVER)
    if isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, 23, 59, tzinfo=VANCOUVER)
    return None


def _kind_and_id(uid, url):
    m = UID_RE.match(uid)
    if m:
        kind = "assignment" if m.group(1) == "assignment" else "event"
        return kind, m.group(2)
    # ponytail: UID didn't match the known Canvas shape (a different school's
    # feed, or a format change) - fall back to the old URL guess rather than
    # crash. No item id means no deep link rebuild either (see _deep_link).
    return ("event" if "/calendar_events/" in url else "assignment"), None


def _deep_link(url, kind, item_id):
    """The item's own page, not the generic calendar page every event's URL
    otherwise shares - rebuilt from the course id already in that URL's
    query string plus UID's item id. Verified against a real self-hosted
    Canvas: an assignment's real page is /courses/<id>/assignments/<id>,
    but a calendar event's is /calendar?event_id=<id>&include_contexts=
    course_<id> - not /courses/<id>/calendar_events/<id>, which looked
    plausible but isn't what Canvas actually links to. Falls back to the
    feed's own (generic, but real) URL when either piece is missing, and
    always includes UID as a fragment so (source, url) stays unique per
    item even then (rule 4)."""
    if item_id is None:
        return url
    course_m = COURSE_ID_RE.search(url)
    if not course_m:
        return f"{url}#{item_id}" if url else ""
    course_id = course_m.group(1)
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if kind == "assignment":
        return f"{base}/courses/{course_id}/assignments/{item_id}"
    return f"{base}/calendar?event_id={item_id}&include_contexts=course_{course_id}"


def parse(ics_text, source):
    """.ics text -> list[Item]. `source` tags where it came from, e.g. "canvas"."""
    items = []
    for event in Calendar.from_ical(ics_text).walk("VEVENT"):
        summary = str(event.get("summary", ""))
        m = COURSE_SUFFIX.search(summary)
        dtstart = event.get("dtstart")
        url = str(event.get("url", ""))
        uid = str(event.get("uid", ""))
        kind, item_id = _kind_and_id(uid, url)
        items.append(Item(
            course=m.group(1) if m else "",
            category=category_for(kind),
            kind=kind,
            title=COURSE_SUFFIX.sub("", summary),
            due=_due(dtstart.dt) if dtstart else None,
            url=_deep_link(url, kind, item_id),
            source=source,
        ))
    return items


def fetch(feed_url, source):
    """Feed URL -> list[Item]. Raises requests.HTTPError on a bad/expired URL.
    No host/size guard - only for a feed URL from a trusted context (e.g.
    already known, not freshly typed by a stranger on the internet). A
    student-submitted URL (POST /api/feed) must go through fetch_untrusted()
    instead."""
    r = requests.get(feed_url, timeout=30)
    r.raise_for_status()
    return parse(r.text, source)


# SSRF guard for /api/feed (#47): a student can paste ANY string here, and
# this fetches it server-side (Canvas sends no CORS headers, so the browser
# can't fetch it directly) - so only a known-safe https host may be reached
# this way, never an arbitrary one.
ALLOWED_FEED_HOSTS = ("canvas.ubc.ca",)
ALLOWED_FEED_HOST_SUFFIXES = (".instructure.com",)
MAX_FEED_BYTES = 5_000_000
FEED_TIMEOUT_S = 15


def is_allowed_feed_host(url):
    """True if `url` is a real https:// URL on the allowlist above, or on
    FEED_ORACLE_HOST (an env var, test-only - our self-hosted Canvas for
    live testing; never set this in production)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname
    oracle_host = os.environ.get("FEED_ORACLE_HOST")
    if oracle_host and host == oracle_host:
        return True
    return host in ALLOWED_FEED_HOSTS or any(host.endswith(s) for s in ALLOWED_FEED_HOST_SUFFIXES)


def fetch_untrusted(url, source):
    """Validate, fetch, parse - the one function both /api/feed
    implementations (hub/api.py for local mode, the Vercel function for the
    hosted site) call, so the host allowlist, size/time limits and redirect
    handling live in exactly one place (rule 1). Never logs `url`, and never
    raises an exception that could contain it (requests' own HTTPError
    embeds the request URL in its message, so it's caught and replaced
    below) - it's a secret, like a token. Every failure raises ValueError
    with a message safe to show on screen."""
    if not is_allowed_feed_host(url):
        raise ValueError("that isn't an allowed Canvas calendar-feed host")
    try:
        r = requests.get(url, timeout=FEED_TIMEOUT_S, stream=True, allow_redirects=False)
    except requests.RequestException:
        raise ValueError("couldn't reach the feed")
    if 300 <= r.status_code < 400:
        # A redirect could point anywhere, including past the host
        # allowlist (e.g. an internal address) - refuse rather than follow
        # it, even to another allowed host.
        raise ValueError("that feed redirected somewhere else")
    if not r.ok:
        raise ValueError(f"feed returned {r.status_code}")
    # requests' `timeout` only bounds a single socket read, not the whole
    # response - a slow-drip server (a few bytes every few seconds) can
    # otherwise hold the connection open far past FEED_TIMEOUT_S. An
    # explicit wall-clock deadline across all chunks closes that gap.
    deadline = time.monotonic() + FEED_TIMEOUT_S
    chunks, total = [], 0
    try:
        for chunk in r.iter_content(chunk_size=65_536):
            total += len(chunk)
            if total > MAX_FEED_BYTES:
                raise ValueError("feed response too large")
            if time.monotonic() > deadline:
                raise ValueError("feed took too long to respond")
            chunks.append(chunk)
    except requests.RequestException:
        raise ValueError("couldn't reach the feed")
    return parse(b"".join(chunks).decode("utf-8", errors="replace"), source)


def to_dict(item, now):
    """Item -> JSON-ready dict, same shape hub/api.py's other endpoints use
    (web/lib/hub.js's normaliseApiItem() expects it) - shared so /api/feed's
    two implementations (hub/api.py, the Vercel function) serialize
    identically, not just parse identically."""
    return {
        "course": item.course, "category": item.category, "kind": item.kind, "title": item.title,
        "due": item.due.isoformat() if item.due else None, "url": item.url, "source": item.source,
        "done": item.done,
        "status": status_of(item, now),
        "urgency": classify_urgency(item.title, item.due, now),
    }


# --- /api/feed's cookie (both implementations: hub/api.py, web/api/feed.py) ---
# The feed URL is a secret, so the browser never keeps it anywhere a script
# can read (it used to sit in localStorage). After one successful POST it
# lives only in an httpOnly cookie scoped to /api/feed, so the page's own JS
# never sees it and no other route receives it. Kept here, next to
# fetch_untrusted(), so the two HTTP front ends can't drift (rule 1).
FEED_COOKIE = "lauds_feed"
FEED_COOKIE_MAX_AGE = 2_592_000  # 30 days
_FEED_COOKIE_ATTRS = "HttpOnly; Secure; SameSite=Strict; Path=/api/feed"


def feed_cookie(url):
    """Set-Cookie value that stores `url` (url-encoded)."""
    return f"{FEED_COOKIE}={quote(url, safe='')}; {_FEED_COOKIE_ATTRS}; Max-Age={FEED_COOKIE_MAX_AGE}"


def clear_feed_cookie():
    """Set-Cookie value that deletes the feed cookie (Disconnect)."""
    return f"{FEED_COOKIE}=; {_FEED_COOKIE_ATTRS}; Max-Age=0"


def feed_url_from_cookie(cookie_header):
    """The feed URL from a request's Cookie header, or None."""
    for part in (cookie_header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == FEED_COOKIE and value:
            return unquote(value)
    return None


def feed_request(method, cookie_header, body=None, now=None):
    """The whole /api/feed behaviour, minus HTTP plumbing. Returns
    (status, payload or None, Set-Cookie value or None).

    - POST {url}: fetch it; only on success, set the cookie.
    - GET: fetch the URL from the cookie; 404 if there isn't one.
    - DELETE: clear the cookie.
    Error payloads never contain the URL (see fetch_untrusted())."""
    if method == "DELETE":
        return 204, None, clear_feed_cookie()
    if method == "GET":
        url = feed_url_from_cookie(cookie_header)
        if not url:
            return 404, {"error": "no feed connected"}, None
    else:
        url = (body or {}).get("url", "")
        if not isinstance(url, str):
            return 400, {"error": "that isn't an allowed Canvas calendar-feed host"}, None
    try:
        items = fetch_untrusted(url, "canvas")
    except ValueError as e:
        return 400, {"error": str(e)}, None
    except Exception:  # ponytail: one broad catch at the boundary - a bad/expired/slow
        # feed shouldn't 500 the server. Generic text: never echo anything that
        # might carry the URL.
        return 502, {"error": "couldn't load the feed"}, None
    now = now or datetime.now(timezone.utc)
    payload = [to_dict(i, now) for i in items]
    return 200, payload, feed_cookie(url) if method == "POST" else None
