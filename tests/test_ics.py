import pytest

from hub import ics
from hub.ics import VANCOUVER, is_allowed_feed_host, parse

# Verified shape from a real self-hosted Canvas feed (#47): every event's URL
# is the *generic* course calendar page, never its own page - items 1 and 2
# share the exact same URL here on purpose, the real bug that broke both
# kind and (source, url) identity before the UID-based fix.
FEED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-99
DTSTART:20260930T065900Z
SUMMARY:Quiz 2 [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-55
DTSTART:20261002T170000Z
SUMMARY:Office hours [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-101
DTSTART;VALUE=DATE:20261005
SUMMARY:Reading week starts [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261010T000000Z
SUMMARY:Untagged item
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-202
DTSTART:20261012T065900Z
SUMMARY:Lab [make-up] [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
END:VCALENDAR
"""


def test_kind_comes_from_uid_not_the_generic_url():
    items = parse(FEED, source="canvas")
    assert [i.kind for i in items[:4]] == ["assignment", "event", "assignment", "assignment"]
    assert [i.category for i in items[:4]] == ["task", "deadline", "task", "task"]
    assert items[0].course == "CPSC 121 101"
    assert items[0].title == "Quiz 2"
    assert items[0].due.day == 30


def test_deep_link_is_rebuilt_from_uid_and_course_id_not_the_generic_url():
    # Verified against a real self-hosted Canvas: an assignment's real page
    # is /courses/<id>/assignments/<id>, but a calendar event's is
    # /calendar?event_id=<id>&include_contexts=course_<id> - not
    # /courses/<id>/calendar_events/<id>, which looked plausible but isn't
    # what Canvas actually links to.
    items = parse(FEED, source="canvas")
    assert items[0].url == "https://canvas.ubc.ca/courses/7/assignments/99"
    assert items[1].url == "https://canvas.ubc.ca/calendar?event_id=55&include_contexts=course_7"


def test_identical_generic_urls_no_longer_collide():
    # Before the fix, items 0 and 1 shared the exact same (source, url) -
    # rule 4's identity - so hub.db upserts would have collapsed them into
    # one row.
    items = parse(FEED, source="canvas")
    assert items[0].url != items[1].url


def test_all_day_event_due_is_end_of_day_vancouver_time():
    # DTSTART;VALUE=DATE has no time component - icalendar hands back a bare
    # `date`. UTC midnight would land on Oct 4 in Vancouver (UTC-7 in
    # October), a day early for something due "Oct 5" - 23:59 America/
    # Vancouver is the actual last moment of that calendar day there.
    items = parse(FEED, source="canvas")
    due = items[2].due
    assert due.tzinfo is not None
    assert (due.year, due.month, due.day, due.hour, due.minute) == (2026, 10, 5, 23, 59)
    assert due.tzinfo == VANCOUVER


def test_naive_datetime_gets_a_timezone_attached():
    # A school's feed with no timezone info at all (not every Moodle feed
    # states one) - a naive datetime here would crash anything comparing it
    # against datetime.now(timezone.utc), e.g. Hide overdue.
    items = parse("""\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART:20261005T235900
SUMMARY:Naive deadline
END:VEVENT
END:VCALENDAR
""", source="moodle")
    assert items[0].due.tzinfo == VANCOUVER


def test_unrecognized_uid_falls_back_without_crashing():
    items = parse(FEED, source="canvas")
    untagged = items[3]
    assert untagged.course == ""
    assert untagged.title == "Untagged item"
    assert untagged.kind == "assignment"  # no URL either -> the old default guess
    assert untagged.url == ""


def test_title_containing_its_own_brackets_still_gets_the_real_course_suffix():
    # Found by the feed oracle: a lazy .+? here matched the FIRST "]" it
    # could reach ("[make-up]"), leaving "[CPSC 121 101]" attached to the
    # title instead of parsed out as the course.
    items = parse(FEED, source="canvas")
    bracketed = items[4]
    assert bracketed.course == "CPSC 121 101"
    assert bracketed.title == "Lab [make-up]"


def test_no_course_suffix_is_fine():
    # Moodle feeds don't tag "[COURSE]" onto the summary.
    items = parse(FEED, source="moodle")
    assert items[3].course == ""
    assert items[3].source == "moodle"


@pytest.mark.parametrize("url,expected", [
    ("https://canvas.ubc.ca/feeds/calendars/abc.ics", True),
    ("https://ubc.instructure.com/feeds/calendars/abc.ics", True),
    ("https://sub.instructure.com/feeds/calendars/abc.ics", True),
    ("http://canvas.ubc.ca/feeds/calendars/abc.ics", False),  # not https
    ("https://evil.example.com/feeds/calendars/abc.ics", False),  # not on the list
    ("https://notcanvas.ubc.ca.evil.com/x", False),  # lookalike host, not a real suffix match
    ("not a url", False),
])
def test_is_allowed_feed_host(url, expected):
    assert is_allowed_feed_host(url) == expected


def test_is_allowed_feed_host_honours_the_test_only_oracle_env_var(monkeypatch):
    monkeypatch.setenv("FEED_ORACLE_HOST", "canvas.selfhost.test")
    assert is_allowed_feed_host("https://canvas.selfhost.test/feeds/calendars/abc.ics") is True
    assert is_allowed_feed_host("https://canvas.selfhost.test/feeds/calendars/abc.ics".replace("https", "http")) is False


def test_fetch_untrusted_rejects_a_disallowed_host_without_ever_requesting_it(monkeypatch):
    called = []
    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: called.append(1))
    with pytest.raises(ValueError):
        ics.fetch_untrusted("https://evil.example.com/feed.ics", "canvas")
    assert called == []  # never made the request at all


class _FakeResponse:
    def __init__(self, status_code=200, chunks=(b"",)):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._chunks = chunks

    def iter_content(self, chunk_size):
        yield from self._chunks


def test_fetch_untrusted_rejects_a_too_large_response(monkeypatch):
    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: _FakeResponse(chunks=[b"x" * (ics.MAX_FEED_BYTES + 1)]))
    with pytest.raises(ValueError):
        ics.fetch_untrusted("https://canvas.ubc.ca/feeds/calendars/abc.ics", "canvas")


def test_fetch_untrusted_parses_a_normal_response(monkeypatch):
    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: _FakeResponse(chunks=[FEED.encode()]))
    items = ics.fetch_untrusted("https://canvas.ubc.ca/feeds/calendars/abc.ics", "canvas")
    assert len(items) == 5
    assert items[0].source == "canvas"


def test_fetch_untrusted_does_not_follow_redirects(monkeypatch):
    # An allowed host could 3xx to an internal address - refusing to follow
    # it at all, rather than checking the destination, is what actually
    # closes that hole (checking the destination just moves the bug).
    seen_kwargs = {}

    def fake_get(*a, **k):
        seen_kwargs.update(k)
        return _FakeResponse(status_code=302)

    monkeypatch.setattr(ics.requests, "get", fake_get)
    with pytest.raises(ValueError):
        ics.fetch_untrusted("https://canvas.ubc.ca/feeds/calendars/abc.ics", "canvas")
    assert seen_kwargs.get("allow_redirects") is False


def test_fetch_untrusted_error_messages_never_contain_the_feed_url(monkeypatch):
    secret_url = "https://canvas.ubc.ca/feeds/calendars/super-secret-user-token.ics"

    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: _FakeResponse(status_code=404))
    with pytest.raises(ValueError) as exc_info:
        ics.fetch_untrusted(secret_url, "canvas")
    assert "super-secret-user-token" not in str(exc_info.value)

    def raise_request_exception(*a, **k):
        raise ics.requests.ConnectionError(f"Failed to reach {secret_url}")

    monkeypatch.setattr(ics.requests, "get", raise_request_exception)
    with pytest.raises(ValueError) as exc_info:
        ics.fetch_untrusted(secret_url, "canvas")
    assert "super-secret-user-token" not in str(exc_info.value)


def test_fetch_untrusted_enforces_a_total_wall_clock_deadline(monkeypatch):
    # requests' own `timeout` only bounds a single socket read - a
    # slow-drip server (a few bytes every few seconds, each read
    # individually "fast enough") could otherwise hold the connection open
    # far past FEED_TIMEOUT_S.
    real_monotonic = ics.time.monotonic
    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        # First call sets the deadline; every call after looks like it's
        # already past it, without a real sleep in the test.
        return real_monotonic() if calls["n"] == 1 else real_monotonic() + ics.FEED_TIMEOUT_S + 1

    monkeypatch.setattr(ics.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: _FakeResponse(chunks=[b"a", b"b", b"c"]))
    with pytest.raises(ValueError):
        ics.fetch_untrusted("https://canvas.ubc.ca/feeds/calendars/abc.ics", "canvas")
