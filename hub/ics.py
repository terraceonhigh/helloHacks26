"""One iCalendar parser for any school's feed (Canvas, Moodle, ...).

Canvas and Moodle both expose a per-student .ics URL (docs/api-standards.md
"Architecture suggestion"). Feed URLs carry a secret, same as a token: never
log or commit one.
"""
import re
from urllib.parse import urlsplit, urlunsplit

import requests
from icalendar import Calendar

from hub.models import Item, category_for

# Canvas puts "[COURSE CODE]" on the end of every event/assignment summary.
# Moodle feeds don't, so course comes back "" there - fine for a first cut.
COURSE_SUFFIX = re.compile(r"\s*\[(.+?)\]\s*$")

# Canvas's own UID shape for planner-backed events, e.g. "event-assignment-99"
# or "event-calendar-event-55". Feeds that don't use it (Moodle, so far) fall
# back to the old URL-sniffing heuristic below.
UID_RE = re.compile(r"^event-(assignment|calendar-event)-(\d+)$")
COURSE_ID_RE = re.compile(r"include_contexts=course_(\d+)")


def _origin(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def parse(ics_text, source, origin=""):
    """.ics text -> list[Item]. `source` tags where it came from, e.g. "canvas".
    `origin` (scheme://host) rebuilds a deep link from Canvas's UID; pass the
    feed URL's own origin, since events live on the same host."""
    items = []
    for event in Calendar.from_ical(ics_text).walk("VEVENT"):
        summary = str(event.get("summary", ""))
        m = COURSE_SUFFIX.search(summary)
        dtstart = event.get("dtstart")
        raw_url = str(event.get("url", ""))
        uid_match = UID_RE.match(str(event.get("uid", "")))
        if uid_match:
            # Canvas's ics `URL` is the generic course-calendar page for every
            # event, assignment or not - the same link for every item in a
            # course, which broke both `kind` (decided by the link) and
            # identity, which is (source, url) (#15/#47). UID is per-item;
            # use it for both instead, and rebuild a real deep link from it.
            kind_key, item_id = uid_match.groups()
            kind = "assignment" if kind_key == "assignment" else "event"
            course_match = COURSE_ID_RE.search(raw_url)
            if kind == "assignment" and course_match:
                url = f"{origin}/courses/{course_match.group(1)}/assignments/{item_id}"
            else:
                url = f"{origin}/calendar?event_id={item_id}"
        else:
            kind = "event" if "/calendar_events/" in raw_url else "assignment"
            url = raw_url
        items.append(Item(
            course=m.group(1) if m else "",
            category=category_for(kind),
            kind=kind,
            title=COURSE_SUFFIX.sub("", summary),
            due=dtstart.dt if dtstart else None,
            url=url,
            source=source,
        ))
    return items


def fetch(feed_url, source):
    """Feed URL -> list[Item]. Raises requests.HTTPError on a bad/expired URL."""
    r = requests.get(feed_url, timeout=30)
    r.raise_for_status()
    return parse(r.text, source, origin=_origin(feed_url))
