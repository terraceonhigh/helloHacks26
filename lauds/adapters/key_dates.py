"""Public UBC key dates (add/drop, tuition, exam period...) - no login, same
for every student. Port of main's hub/key_dates.py: hand-maintained from the
UBC Academic Calendar for now (not scraped - there's no login behind this
provider to distinguish per-student state), swap for a scraper later without
touching fetch()'s signature.

NAME is "ubc_key_dates", not the module's own name: it's what main's
`Item.source` uses, and the identity items are matched on (source, url) -
matching main's own choice keeps every existing (source, url) upsert intact.

KEY_DATES is keyed by campus, so a new campus is a new dict entry, never a
code change here or in fetch().
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from lauds.models import Bundle, Course, Item, category_for

NAME = "ubc_key_dates"
DESCRIPTION = "UBC key dates: tuition instalments, add/drop, exam period (public, no login)"

CAMPUS_NAMES = {
    "UBCV": "UBC Vancouver",
    "UBCO": "UBC Okanagan",
}

# Sources: UBC Academic Calendar, "Policies on Fees" (vancouver.calendar.ubc.ca
# and okanagan.calendar.ubc.ca /fees/policies-fees) - both campuses publish the
# same instalment-deadline wording for the 2026 Winter Session (main's own
# comment, unchanged here). One polite live GET of the UBCV page on
# 2026-09-28 (tests/fixtures/key_dates/live_ubcv_fees_policy.html) confirms
# "Winter Session 2026/27 Term 1 September 9, 2026 Term 2 January 6, 2027" is
# still exactly what's published - this adapter is "docs-verified" against
# that page (BRIEF.md grading), not "live-verified": there's no self-hosted
# stand-in for the UBC Academic Calendar, and there's no parser to replay the
# fixture through either - the data here is hand-maintained, not scraped.
# UBCO's page publishes the identical wording per main's original comment;
# not independently re-fetched, to keep this to one polite request.
#
# Each entry's real source page is the same "Policies on Fees" URL for its
# campus, but item identity is (source, url) - so every entry needs its own
# url or one upsert would silently overwrite the other. A #fragment is
# enough: it's never fetched, just an identity key. `due` is Vancouver
# wall-clock time with no offset; fetch() attaches America/Vancouver so
# tzdata picks PDT/PST per date instead of a hand-typed offset.
VAN = ZoneInfo("America/Vancouver")
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


def parse(campus: str, term: str, now: datetime) -> tuple[Course, list[Item]]:
    """The pure heart of this adapter: KEY_DATES + a campus + a clock ->
    (Course, [Item]). The campus itself stands in as a "course" (its dates
    aren't tied to any one class), so it joins and displays like any other
    course instead of landing as "(unknown course)".

    A date that has passed comes back done=True, not overdue: it's public
    and the same for every student, so lauds can't know whether they've
    actually paid. Before then done=None (unknown), so it reminds like any
    other deadline."""
    course = Course(code=campus, section="", term=term, title=CAMPUS_NAMES.get(campus, campus), source=NAME)
    items = []
    for d in KEY_DATES.get(campus, []):
        due = datetime.fromisoformat(d["due"]).replace(tzinfo=VAN)
        # ponytail: "passed" == "done" only because there's no per-student
        # fees login behind this provider. Upgrade: take done from Workday's
        # account balance once that adapter can report it.
        items.append(Item(course=campus, category=category_for(d["kind"]), kind=d["kind"], title=d["title"],
                           due=due, url=d["url"], source=NAME, done=True if due < now else None))
    return course, items


def fetch(campus: str = "UBCV", term: str = "2026W1", now: datetime | None = None) -> Bundle:
    now = now or datetime.now(VAN)
    course, items = parse(campus, term, now)
    return Bundle(courses=[course], items=items)
