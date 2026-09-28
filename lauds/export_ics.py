"""Export the shared model as one merged .ics feed - port of main's
hub/export_ics.py (BRIEF.md: "export ics ... port main's hub/export_ics.py").

Kept field-for-field and byte-for-byte compatible with the oracle
(tests/oracle/export_ics/*.json, checked by tests/parity/test_export_ics.py):
same PRODID/X-WR-CALNAME, same per-kind colour table, same UID scheme (a
stable hash of (source, url), so re-subscribing updates events instead of
duplicating them), same two-alarm (T-2d, T-0d) pattern, same "Title [COURSE]"
SUMMARY convention that a Canvas .ics feed's own inbound parser (a separate
adapter's job) can read a course code back out of.
"""
import hashlib
from datetime import timedelta

from icalendar import Alarm, Calendar, Event

ALARM_DAYS_BEFORE = (2, 0)

KIND_COLORS = {
    "assignment": "#2563EB",
    "quiz": "#7C3AED",
    "exam": "#DC2626",
    "reading": "#059669",
    "textbook": "#059669",
    "announcement": "#64748B",
    "event": "#D97706",
    "break": "#D97706",
    "payment": "#CA8A04",
}
KIND_COLOR_FALLBACK = "#6B7280"


def color_for_kind(kind: str) -> str:
    return KIND_COLORS.get(kind, KIND_COLOR_FALLBACK)


def _label_for(kind: str) -> str:
    return kind.replace("_", " ").title()


def known_kinds(items) -> list[str]:
    """Every distinct `kind` among items with a due date, sorted."""
    return sorted({i.kind for i in items if i.due is not None})


def uid_for(item) -> str:
    """Stable across re-exports: a hash of (source, url), not a counter."""
    digest = hashlib.sha1(f"{item.source}:{item.url}".encode()).hexdigest()[:16]
    return f"{item.source}-{digest}@ubchub"


def _alarm(days_before: int, summary: str) -> Alarm:
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", summary)
    alarm.add("trigger", timedelta(days=-days_before))
    return alarm


def to_ics(items, kind: str | None = None) -> bytes:
    """[Item] -> one .ics feed, as bytes. Items with no due date are
    skipped (there's no date to put a calendar event on). `kind`, if given,
    keeps only items of that one kind, so subscribing to several per-kind
    feeds side by side is how a calendar app gives each its own colour
    (iCalendar has no portable per-event colour property)."""
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
        event.add("uid", uid_for(item))
        event.add("summary", summary)
        event.add("dtstart", item.due)
        event.add("categories", [_label_for(item.kind)])
        if item.url:
            event.add("url", item.url)
        for days_before in ALARM_DAYS_BEFORE:
            event.add_component(_alarm(days_before, summary))
        cal.add_component(event)
    return cal.to_ical()
