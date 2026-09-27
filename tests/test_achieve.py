"""Tests for hub/achieve.py.

There is no real Achieve markup or JSON to test against (see the module
docstring), so these tests only cover what's actually implemented:
`fetch()` always degrading to the safe, empty result, and `login()` reusing
`hub.site.login` the same way every other browser-session adapter does.
"""
from hub import achieve


def test_fetch_returns_no_courses_and_no_items():
    # Intentional, not a placeholder bug -- see hub/achieve.py's module
    # docstring for exactly why nothing is parsed yet.
    courses, items = achieve.fetch()
    assert courses == []
    assert items == []


def test_fetch_accepts_a_base_override_and_still_returns_empty():
    courses, items = achieve.fetch("https://achieve.macmillanlearning.com/course/abc123")
    assert (courses, items) == ([], [])


def test_login_reuses_the_shared_browser_session_core(monkeypatch):
    calls = []
    monkeypatch.setattr(achieve.site, "login", lambda site_name, base: calls.append((site_name, base)))

    achieve.login()

    assert calls == [("achieve", achieve.BASE)]


def test_login_passes_through_a_custom_base(monkeypatch):
    calls = []
    monkeypatch.setattr(achieve.site, "login", lambda site_name, base: calls.append((site_name, base)))

    achieve.login("https://achieve.macmillanlearning.com/course/xyz789")

    assert calls == [("achieve", "https://achieve.macmillanlearning.com/course/xyz789")]
