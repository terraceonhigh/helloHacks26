"""Public UBC key dates (add/drop, tuition, exam period...) - no login, same
for every student (design.md's "UBC key dates" provider). Hand-maintained
from the UBC Academic Calendar for now; swap for a scraper later without
touching fetch()'s signature.

KEY_DATES is keyed by campus so a new campus - or a new school entirely -
is just a new dict entry, never a code change here or in fetch().
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from hub.models import Course, Item, category_for

CAMPUS_NAMES = {
    "UBCV": "UBC Vancouver",
    "UBCO": "UBC Okanagan",
}

# Sources: UBC Academic Calendar, "Policies on Fees" (vancouver.calendar.ubc.ca
# and okanagan.calendar.ubc.ca /fees/policies-fees) - both campuses publish
# the same instalment-deadline wording for 2026 Winter Session.
# Each entry's real source page is the same "Policies on Fees" URL for its
# campus - but hub.db's item identity is (source, url) (AGENTS.md rule 4),
# so every entry still needs its OWN url or one upsert silently overwrites
# the other. A #fragment is enough: it's never fetched, just an identity key.
# `due` is Vancouver wall-clock time, no offset: fetch() attaches VAN, so
# tzdata picks PDT/PST per date instead of a hand-typed offset.
VAN = ZoneInfo("America/Vancouver")  # both campuses are Pacific time
KEY_DATES = {
    "UBCV": [
        {"title": "Tuition: 1st instalment due (Winter Session)", "kind": "payment",
         "due": "2026-09-09T23:59",
         "url": "https://vancouver.calendar.ubc.ca/fees/policies-fees#1st-instalment-2026w1"},
        {"title": "Tuition: 2nd instalment due (Winter Session)", "kind": "payment",
         "due": "2027-01-06T23:59",
         "url": "https://vancouver.calendar.ubc.ca/fees/policies-fees#2nd-instalment-2026w1"},
    ],
    "UBCO": [
        {"title": "Tuition: 1st instalment due (Winter Session)", "kind": "payment",
         "due": "2026-09-09T23:59",
         "url": "https://okanagan.calendar.ubc.ca/fees/policies-fees#1st-instalment-2026w1"},
        {"title": "Tuition: 2nd instalment due (Winter Session)", "kind": "payment",
         "due": "2027-01-06T23:59",
         "url": "https://okanagan.calendar.ubc.ca/fees/policies-fees#2nd-instalment-2026w1"},
    ],
}


def fetch(campus="UBCV", term="2026W1", now=None):
    """(list[Course], list[Item]) for one campus's key dates - same shape
    every adapter returns. The campus itself stands in as a "course" (its
    dates aren't tied to any one class), so they join and display like any
    other course instead of landing as "(unknown course)".

    A date that has passed comes back done=True, not overdue: it's public
    and the same for everyone, so Hub can't know whether this student acted
    on it. Before then done=None (unknown), so it reminds like any deadline."""
    now = now or datetime.now(VAN)
    course = Course(code=campus, section="", term=term, title=CAMPUS_NAMES.get(campus, campus))
    items = []
    for d in KEY_DATES.get(campus, []):
        due = datetime.fromisoformat(d["due"]).replace(tzinfo=VAN)
        # ponytail: "passed" == "done" because there's no per-student fees
        # login behind this provider. Upgrade: take done from Workday's
        # account balance once that adapter lands.
        items.append(Item(course=campus, category=category_for(d["kind"]), kind=d["kind"], title=d["title"],
                          due=due, url=d["url"], source="ubc_key_dates", done=True if due < now else None))
    return [course], items
