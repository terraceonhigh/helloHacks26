"""Network-free checks of tests/live/canvas_feed_oracle.compare itself."""
from datetime import date, datetime, timezone

from hub.models import Item, category_for
from tests.live.canvas_feed_oracle import Truth, compare

B = "https://canvas.example.test"
FEED = f"""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-10
DTSTART:20261016T065900Z
SUMMARY:FAKE [lab] essay [FAKE 101 001]
URL;VALUE=URI:{B}/calendar?include_contexts=course_7&month=10&year=2026#assignment_10
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-3
DTSTART:20261014T220000Z
SUMMARY:FAKE office hours [FAKE 101 001]
URL;VALUE=URI:{B}/calendar?include_contexts=course_7&month=10&year=2026#calendar_event_3
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-12
DTSTART;VALUE=DATE:20270106
SUMMARY:FAKE all-day [FAKE 101 001]
URL;VALUE=URI:{B}/calendar?include_contexts=course_7&month=01&year=2027#assignment_12
END:VEVENT
END:VCALENDAR
"""
UTC = timezone.utc
TRUTH = [
    Truth("assignment", 10, "FAKE [lab] essay", "FAKE 101 001", datetime(2026, 10, 16, 6, 59, 30, tzinfo=UTC),
          f"{B}/courses/7/assignments/10"),
    Truth("event", 3, "FAKE office hours", "FAKE 101 001", datetime(2026, 10, 14, 22, tzinfo=UTC),
          f"{B}/calendar?event_id=3&include_contexts=course_7"),
    Truth("assignment", 12, "FAKE all-day", "FAKE 101 001", datetime(2027, 1, 7, 6, 59, tzinfo=UTC),
          f"{B}/courses/7/assignments/12"),
    Truth("assignment", 13, "FAKE undated", "FAKE 101 001", None, f"{B}/courses/7/assignments/13"),
]


def item(title, kind, due, url):
    return Item(course="FAKE 101 001", category=category_for(kind), kind=kind, title=title, due=due,
                url=url, source="canvas")


def good():
    return [item(t.title, t.kind, t.due.replace(second=0), t.url) for t in TRUTH[:3]]


def statuses(result, check):
    return [r.cells[check][0] for r in result.rows]


def test_correct_parse_has_no_fail():
    r = compare(FEED, good(), TRUTH)
    assert r.fails() == 0
    # undated assignment is absent from the feed: INFO, not FAIL
    assert any(s == "INFO" and "undated" in m for s, m in r.notes)
    assert any(s == "INFO" and "seconds" in m for s, m in r.notes)


def test_generic_url_and_wrong_kind_fail():
    generic = f"{B}/calendar?include_contexts=course_7"
    bad = [item(t.title, "assignment", t.due.replace(second=0), generic) for t in TRUTH[:3]]
    r = compare(FEED, bad, TRUTH)
    assert statuses(r, "url") == ["FAIL"] * 3
    assert statuses(r, "kind") == ["PASS", "FAIL", "PASS"]
    assert any(s == "FAIL" and "not unique" in m for s, m in r.notes)


def test_bracketed_title_and_date_only_due_fail():
    bad = good()
    bad[0].title, bad[0].course = "", "lab] essay [FAKE 101 001"
    bad[2].due = date(2027, 1, 6)
    r = compare(FEED, bad, TRUTH)
    assert statuses(r, "title") == ["FAIL", "PASS", "PASS"]
    assert statuses(r, "course") == ["FAIL", "PASS", "PASS"]
    assert statuses(r, "due") == ["PASS", "PASS", "FAIL"]


def test_all_day_wrong_instant_same_date_is_warn():
    it = good()
    it[2].due = datetime(2027, 1, 6, 12, tzinfo=UTC)  # same Vancouver date, not 23:59
    r = compare(FEED, it, TRUTH)
    assert statuses(r, "due")[2] == "WARN"
    assert r.fails() == 0
