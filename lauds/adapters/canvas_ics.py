"""Canvas's per-student .ics calendar feed - no login needed, just the
feed's own secret URL (Canvas > Calendar > Calendar Feed). Clean port of
main's hub/ics.py, scoped to Canvas by this task (BRIEF.md); `parse()` takes
`source` as a parameter and adds no Canvas-only assumption beyond the
"[COURSE CODE]" suffix Canvas puts on every summary (a feed that doesn't
have one, e.g. Moodle's, just comes back with course=""), so a future
`moodle_ics` adapter can reuse it without touching this file (rule 1: no
provider special-cased outside its own adapter).

Verified against a real self-hosted Canvas (instructure/canvas-lms): every
event's URL is the *generic* course calendar page
(.../calendar?include_contexts=course_N), never the item's own page. UID
carries the real signal instead (Canvas's own
event-assignment-<id>/event-calendar-event-<id> format); the deep link is
rebuilt from that id plus the course id already sitting in the generic
URL's query string.

The feed URL is a secret, like a password or token: never log, print or
commit it. `lauds login canvas_ics <url>` stores it 0600 under
~/.config/lauds/ (paths.config_dir()), never in the database - `fetch()`
reads it back from there, never taking a bare URL on the command line by
default (a shell history is not 0600).
"""
import os
import re
import time
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar

from lauds import paths
from lauds.models import Bundle, Item, category_for

NAME = "canvas_ics"
DESCRIPTION = "Canvas (or Moodle) .ics calendar feed"
VANCOUVER = ZoneInfo("America/Vancouver")

# Canvas puts "[COURSE CODE]" on the end of every event/assignment summary.
# Moodle feeds don't, so course comes back "" there. [^\[\]]+, not a lazy
# .+?: a title that itself contains "[...]" needs the LAST bracket group
# specifically, and a negated class gets that in one linear pass instead of
# backtracking through nested brackets (also avoids a ReDoS shape on
# adversarial input).
COURSE_SUFFIX = re.compile(r"\s*\[([^\[\]]+)\]\s*$")
# Canvas's own UID shape for a calendar-feed VEVENT.
UID_RE = re.compile(r"^event-(assignment|calendar-event)-(\d+)$")
# The course id sitting in the generic URL every feed item currently ships
# with (.../calendar?include_contexts=course_12345).
COURSE_ID_RE = re.compile(r"course_(\d+)")

# SSRF guard: a feed URL only ever comes from the student's own paste/login,
# but it's still worth refusing to fetch anything that isn't a real feed
# host - a stale or mistyped config value should fail loudly, not silently
# hit an unrelated address.
ALLOWED_FEED_HOSTS = ("canvas.ubc.ca",)
ALLOWED_FEED_HOST_SUFFIXES = (".instructure.com",)
MAX_FEED_BYTES = 5_000_000
FEED_TIMEOUT_S = 15


def _feed_path():
    return paths.config_dir() / "canvas_ics-feed"


def login(feed_url, **opts):
    """Save a feed URL, 0600, under lauds' config dir. Rejects anything not
    on the host allowlist up front, so a bad paste is caught immediately."""
    if not is_allowed_feed_host(feed_url):
        raise ValueError("that isn't an allowed Canvas calendar-feed host")
    path = _feed_path()
    paths.ensure_dir(path.parent)
    paths.secure_write_text(path, feed_url)  # 0600 from creation - the URL is a secret, like a token
    return path


def is_allowed_feed_host(url):
    """True if `url` is a real https:// URL on the allowlist above, or on
    FEED_ORACLE_HOST (an env var, test-only - self-hosted Canvas for live
    testing; never set this in production)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname
    oracle_host = os.environ.get("FEED_ORACLE_HOST")
    if oracle_host and host == oracle_host:
        return True
    return host in ALLOWED_FEED_HOSTS or any(host.endswith(s) for s in ALLOWED_FEED_HOST_SUFFIXES)


def _due(dt):
    """dtstart.dt is a bare `date` for an all-day event (no time component) -
    treated as due at the end of that day, Vancouver time: UTC midnight is
    the *previous* calendar day there for most of the year, which would put
    a "due today" item a day early. A naive datetime (a feed that doesn't
    state a timezone at all) gets the same zone attached rather than
    staying naive, which would crash anything comparing it against
    datetime.now(timezone.utc). An already-aware datetime passes through
    unchanged."""
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
    # crash. No item id means no deep link rebuild either.
    return ("event" if "/calendar_events/" in url else "assignment"), None


def _deep_link(url, kind, item_id):
    """The item's own page, not the generic calendar page every event's URL
    otherwise shares - rebuilt from the course id already in that URL's
    query string plus UID's item id. Verified against a real self-hosted
    Canvas: an assignment's real page is /courses/<id>/assignments/<id>, but
    a calendar event's is /calendar?event_id=<id>&include_contexts=
    course_<id>. Falls back to the feed's own (generic, but real) URL when
    either piece is missing, and always includes the item id as a fragment
    so (source, url) stays unique per item even then."""
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
    """.ics text -> list[Item]. `source` tags where it came from (e.g. "canvas")."""
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


def fetch_untrusted(url, source):
    """Validate, fetch, parse. Never logs `url`, and never raises an
    exception that could contain it (requests' own HTTPError embeds the
    request URL in its message) - it's a secret, like a token. Every
    failure raises ValueError with a message safe to show on screen."""
    if not is_allowed_feed_host(url):
        raise ValueError("that isn't an allowed Canvas calendar-feed host")
    try:
        r = requests.get(url, timeout=FEED_TIMEOUT_S, stream=True, allow_redirects=False)
    except requests.RequestException:
        raise ValueError("couldn't reach the feed")
    if 300 <= r.status_code < 400:
        # A redirect could point anywhere, including past the host
        # allowlist - refuse rather than follow it, even to another
        # allowed host.
        raise ValueError("that feed redirected somewhere else")
    if not r.ok:
        raise ValueError(f"feed returned {r.status_code}")
    # requests' `timeout` only bounds a single socket read, not the whole
    # response - a slow-drip server could otherwise hold the connection
    # open far past FEED_TIMEOUT_S. An explicit wall-clock deadline across
    # all chunks closes that gap.
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


def fetch(feed_url=None, *, source="canvas"):
    """Read the stored feed URL (or `feed_url`, for tests/scripts) and
    return a Bundle. Raises FileNotFoundError if nothing is configured yet -
    the CLI should point the student at `lauds login canvas_ics <url>`."""
    if feed_url is None:
        path = _feed_path()
        if not path.exists():
            raise FileNotFoundError(
                "no Canvas calendar feed configured; run `lauds login canvas_ics <feed url>`")
        feed_url = path.read_text(encoding="utf-8").strip()
    return Bundle(items=fetch_untrusted(feed_url, source))
