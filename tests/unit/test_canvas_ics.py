"""Behavioural port of main's tests/test_ics.py, against
lauds.adapters.canvas_ics. Not ported: the /api/feed cookie plumbing
(feed_cookie/clear_feed_cookie/feed_url_from_cookie/feed_request/to_dict) -
that was hub/api.py's local HTTP server, thrown out per BRIEF.md; login()
(saving the feed URL 0600) and the store round trip are covered here
instead, since a CLI has no cookie to keep it in.
"""
import pytest

from lauds.adapters import canvas_ics as ics
from lauds.adapters.canvas_ics import VANCOUVER, is_allowed_feed_host, parse

# Verified shape from a real self-hosted Canvas feed: every event's URL is
# the *generic* course calendar page - items 1 and 2 share the exact same
# URL here on purpose, the real bug that broke both kind and (source, url)
# identity before the UID-based fix.
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
    items = parse(FEED, source="canvas")
    assert items[0].url == "https://canvas.ubc.ca/courses/7/assignments/99"
    assert items[1].url == "https://canvas.ubc.ca/calendar?event_id=55&include_contexts=course_7"


def test_identical_generic_urls_no_longer_collide():
    items = parse(FEED, source="canvas")
    assert items[0].url != items[1].url


def test_all_day_event_due_is_end_of_day_vancouver_time():
    items = parse(FEED, source="canvas")
    due = items[2].due
    assert due.tzinfo is not None
    assert (due.year, due.month, due.day, due.hour, due.minute) == (2026, 10, 5, 23, 59)
    assert due.tzinfo == VANCOUVER


def test_naive_datetime_gets_a_timezone_attached():
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
    assert untagged.kind == "assignment"
    assert untagged.url == ""


def test_title_containing_its_own_brackets_still_gets_the_real_course_suffix():
    items = parse(FEED, source="canvas")
    bracketed = items[4]
    assert bracketed.course == "CPSC 121 101"
    assert bracketed.title == "Lab [make-up]"


def test_no_course_suffix_is_fine():
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
    assert called == []


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
    real_monotonic = ics.time.monotonic
    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        return real_monotonic() if calls["n"] == 1 else real_monotonic() + ics.FEED_TIMEOUT_S + 1

    monkeypatch.setattr(ics.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(ics.requests, "get", lambda *a, **k: _FakeResponse(chunks=[b"a", b"b", b"c"]))
    with pytest.raises(ValueError):
        ics.fetch_untrusted("https://canvas.ubc.ca/feeds/calendars/abc.ics", "canvas")


# --- lauds-only: config-file storage instead of hub/api.py's cookie -------

def test_login_saves_a_0600_feed_file_and_fetch_reads_it_back(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    path = ics.login("https://canvas.ubc.ca/feeds/calendars/abc.ics")
    assert path.read_text(encoding="utf-8") == "https://canvas.ubc.ca/feeds/calendars/abc.ics"
    assert (path.stat().st_mode & 0o777) in (0o600, 0o700)  # best-effort chmod on non-POSIX storage

    monkeypatch.setattr(ics, "fetch_untrusted", lambda url, source: parse(FEED, source))
    bundle = ics.fetch()
    assert len(bundle.items) == 5


def test_login_rejects_a_disallowed_host_and_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        ics.login("https://evil.example.com/feed.ics")
    assert not ics._feed_path().exists()


def test_fetch_without_login_reports_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="lauds login canvas_ics"):
        ics.fetch()
