"""Canvas (or Moodle) .ics calendar feed adapter -- the no-token fallback (#8).

The feed URL has a secret in it, so treat it like a password: never log it,
print it, put it in another URL, or write it to disk (AGENTS.md rule 3).

Canvas's feed omits To-Do items but includes assignments and calendar events
(docs/api-standards.md, "ICS fallback"). Canvas tags each VEVENT's SUMMARY with
the course in brackets, e.g. "Problem Set 2 [CPSC 110 101]" -- we pull that
raw tag out as-is; turning it into a real course_key is
hub.logic.normalise_course_code()'s job (Sam's #2), not this adapter's.
"""

import re

import requests
from icalendar import Calendar

from hub.models import Item
from hub.net import get_text as _get

_COURSE_TAG_RE = re.compile(r"\[([^\[\]]+)\]\s*$")


def fetch(feed_url):
    """GET an .ics feed URL and parse it into Items. Never log `feed_url`.

    Returns [] (not an exception) if the feed can't be reached, or if what
    comes back isn't valid .ics (e.g. a login page, if the feed URL has
    expired) -- a bad feed degrades to "no items", not a crashed dashboard.
    """
    try:
        text = _get(feed_url)
    except requests.RequestException:
        return []
    try:
        return parse_ics(text)
    except ValueError:
        return []


def parse_ics(ics_text):
    """Parse .ics text (bytes or str) into a list of Items, source="ics"."""
    cal = Calendar.from_ical(ics_text)
    items = []
    for component in cal.walk("VEVENT"):
        item = _to_item(component)
        if item is not None:
            items.append(item)
    return items


def _to_item(vevent):
    uid = str(vevent.get("uid", ""))
    summary = str(vevent.get("summary", "")).strip()
    if not summary:
        return None

    dtstart = vevent.get("dtstart")
    due = dtstart.dt if dtstart is not None else None
    # An all-day (date-only, not datetime) DTSTART has no time zone; icalendar
    # gives us a plain `date` in that case. Leave it as-is -- the UI/logic
    # layer decides how to display a dateless due day.

    url = str(vevent.get("url", "")) or None

    title, course_tag = _split_course_tag(summary)
    kind = _guess_kind(uid, title)

    return Item(
        id=f"ics:event:{uid}" if uid else f"ics:event:{title}:{due}",
        course_key=course_tag,  # raw "CPSC 121 101"-style tag; normalise later
        kind=kind,
        title=title,
        due=due,
        url=url,
        source="ics",
        done=False,
    )


def _split_course_tag(summary):
    """"Problem Set 2 [CPSC 110 101]" -> ("Problem Set 2", "CPSC 110 101")."""
    match = _COURSE_TAG_RE.search(summary)
    if not match:
        return summary, None
    return summary[: match.start()].strip(), match.group(1).strip()


def _guess_kind(uid, title):
    low = title.lower()
    if "exam" in low or "midterm" in low or "final" in low:
        return "exam"
    if "quiz" in low:
        return "quiz"
    if "assignment" in uid.lower():
        return "assignment"
    return "event"
