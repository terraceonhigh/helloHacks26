"""Export the shared model as one merged .ics feed a student can subscribe to
from Apple/Google/Outlook Calendar (#18) - the cheapest way into a routine
they already have, and the reverse direction of hub/ics.py's inbound parser.

**Colour-coordination, and why it's a second feed, not a fancier title.**
Plain iCalendar has no portable per-event colour property: Google, Apple and
Outlook Calendar all colour a whole *subscribed calendar*, never individual
events inside one feed. So `to_ics(items, kind=...)` filters to one kind -
subscribing to several of these side by side is the one thing that reliably
gives each its own distinct colour everywhere, since colour-per-calendar is
universal where colour-per-event isn't. Every event also gets a real
iCalendar `CATEGORIES` property (for Apple Calendar/Outlook, which do use it)
- this is additive and doesn't touch `SUMMARY`/`DTSTART`/`URL`/`UID`, so it
can't affect the round-trip through `hub.ics.parse()` that tests/
test_export_ics.py already checks (parse() never reads CATEGORIES).

Try it:  uv run python -m hub.export_ics [kind]
"""
import hashlib
from datetime import timedelta

from icalendar import Alarm, Calendar, Event

# Two reminders per item, matching the pattern from Terrace's own
# course-deadline calendars: a heads-up two days out, and one on the day.
ALARM_DAYS_BEFORE = (2, 0)

# One colour per `kind`, best-effort - `kind` is free-form (hub/models.py:
# new providers can add one without touching this file), so this can never
# be exhaustive. Not a real iCalendar property (there isn't a portable one -
# see module docstring): for a UI's own swatch/legend next to the per-kind
# feed links, and the CATEGORIES text on each event.
KIND_COLORS = {
    "assignment": "#2563EB",  # blue
    "quiz": "#7C3AED",  # violet
    "exam": "#DC2626",  # red - covers midterms/finals; no separate kind exists for those
    "reading": "#059669",  # green
    "textbook": "#059669",
    "announcement": "#64748B",  # slate
    "event": "#D97706",  # amber
    "break": "#D97706",
    "payment": "#CA8A04",  # yellow
}
KIND_COLOR_FALLBACK = "#6B7280"


def color_for_kind(kind):
    """The best-effort colour for one `kind` - see module docstring for why
    this can't be a real per-event iCalendar colour."""
    return KIND_COLORS.get(kind, KIND_COLOR_FALLBACK)


def _label_for(kind):
    return kind.replace("_", " ").title()


def known_kinds(items):
    """Every distinct `kind` among items with a due date, for a UI to build
    a per-kind-feed picker from without hardcoding a kind list."""
    return sorted({i.kind for i in items if i.due is not None})


def _uid(item):
    """Stable across re-exports: a hash of the item's own (source, url)
    identity (rule 4), not a counter that resets between runs - re-importing
    the same feed updates existing calendar events instead of duplicating
    them."""
    digest = hashlib.sha1(f"{item.source}:{item.url}".encode()).hexdigest()[:16]
    return f"{item.source}-{digest}@ubchub"


def _alarm(days_before, summary):
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", summary)
    alarm.add("trigger", timedelta(days=-days_before))
    return alarm


def to_ics(items, kind=None):
    """[Item] -> one .ics feed, as bytes. Items with no due date are skipped
    - there's no date to put a calendar event on (they still show up in the
    dashboard itself, just not here). `kind`, if given, keeps only items of
    that one kind - see module docstring for why that's the real
    colour-coordination mechanism, not a fancier title.

    Titles get Canvas's own "Title [COURSE]" bracket suffix - the exact
    convention hub.ics.parse() already reads a course code out of, so this
    feed round-trips back through our own inbound parser (tests/
    test_export_ics.py), not just out to a phone's calendar app. (The
    per-kind CATEGORIES property doesn't affect that - parse() never reads
    it.)"""
    cal = Calendar()
    cal.add("prodid", "-//UBC Hub//ubchub//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", f"Lauds: {_label_for(kind)}" if kind else "Lauds")
    for item in items:
        if item.due is None:
            continue
        if kind is not None and item.kind != kind:
            continue
        summary = f"{item.title} [{item.course}]" if item.course else item.title
        event = Event()
        event.add("uid", _uid(item))
        event.add("summary", summary)
        event.add("dtstart", item.due)
        event.add("categories", [_label_for(item.kind)])
        if item.url:
            event.add("url", item.url)
        for days_before in ALARM_DAYS_BEFORE:
            event.add_component(_alarm(days_before, summary))
        cal.add_component(event)
    return cal.to_ical()


if __name__ == "__main__":
    import sys
    from datetime import datetime

    from hub import db
    from hub.models import Item

    conn = db.connect()
    items = [
        Item(course=code, category=category, kind=row_kind, title=title,
             due=datetime.fromisoformat(due) if due else None, url=url, source=source,
             done=bool(done) if done is not None else None)
        for code, category, row_kind, title, due, url, done, source in db.upcoming(conn)
    ]
    only_kind = sys.argv[1] if len(sys.argv) > 1 else None
    print(to_ics(items, kind=only_kind).decode())
