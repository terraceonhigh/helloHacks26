"""Unit tests for lauds.adapters.moodle. main has no dedicated
tests/test_moodle.py (module docstring: [UNVERIFIED END-TO-END], no live
account anywhere on that project) - these port its documented behaviour
(sesskey extraction, kind mapping, url fallback, capture validation) plus
the two real bugs found against a live self-hosted Moodle 4.5
(tests/live/moodle_selfhost/README.md) that this port fixes: never batching
core_enrol_get_users_courses with the calendar call, and capping
`limitnum` at 50."""
import json

import pytest

from lauds.adapters import moodle
from lauds.models import Item

CPSC101_EVENT = {
    "id": 9, "name": "Quiz", "modulename": "quiz", "timesort": 1798000000,
    "url": "", "course": {"shortname": "CPSC101"},
}


def test_to_item_maps_quiz_kind_and_falls_back_to_calendar_event_url():
    i = moodle.to_item(CPSC101_EVENT)
    assert isinstance(i, Item)
    assert (i.category, i.kind, i.course) == ("deadline", "quiz", "CPSC101")
    assert i.due.isoformat() == "2026-12-23T04:26:40+00:00"
    assert i.url == "calendar/event.php?id=9"
    assert i.source == "moodle"


def test_to_item_defaults_unknown_modulename_to_assignment():
    e = {"id": 10, "name": "HW1", "modulename": "assign", "timesort": 1798100000,
         "url": "https://moodle.example.edu/mod/assign/view.php?id=10", "course": {"shortname": "CPSC101"}}
    i = moodle.to_item(e)
    assert (i.category, i.kind) == ("task", "assignment")
    assert i.url == "https://moodle.example.edu/mod/assign/view.php?id=10"  # a real url is used as-is


def test_to_item_due_is_none_without_a_timesort():
    i = moodle.to_item({**CPSC101_EVENT, "timesort": None})
    assert i.due is None


def test_to_item_due_is_never_naive():
    assert moodle.to_item(CPSC101_EVENT).due.tzinfo is not None


def test_to_item_fallback_url_is_absolute_against_base_when_given():
    i = moodle.to_item(CPSC101_EVENT, base="https://moodle.example.edu")
    assert i.url == "https://moodle.example.edu/calendar/event.php?id=9"


def test_to_item_fallback_url_never_synthesizes_a_ambiguous_id_none():
    i = moodle.to_item({**CPSC101_EVENT, "id": None}, base="https://moodle.example.edu")
    assert "id=None" not in i.url


def test_extract_sesskey_finds_the_mcfg_value():
    page = '<script>M.cfg = {"wwwroot":"https:\\/\\/x","sesskey":"AbCd1234"};</script>'
    assert moodle.extract_sesskey(page) == "AbCd1234"


def test_extract_sesskey_none_when_absent_session_not_logged_in():
    assert moodle.extract_sesskey("<html>login page</html>") is None


def test_courses_from_events_dedupes_by_shortname_in_first_seen_order():
    events = [
        {"course": {"shortname": "CPSC101", "fullname": "Intro"}},
        {"course": {"shortname": "MATH200", "fullname": "Calc"}},
        {"course": {"shortname": "CPSC101", "fullname": "Intro"}},
    ]
    courses = moodle._courses_from_events(events)
    assert [c.code for c in courses] == ["CPSC101", "MATH200"]


def test_courses_from_events_skips_an_event_with_no_course():
    assert moodle._courses_from_events([{"course": {}}]) == []


class _Resp:
    def __init__(self, text, status=200):
        self._text = text
        self.status = status
        self.ok = status < 400

    def text(self):
        return self._text


class _FakeReq:
    """A minimal req that records every call methodname and lets a test
    script canned responses per call, so _run's "never batch" rule
    (module docstring) can be asserted directly."""

    def __init__(self, my_html, responses):
        self.my_html = my_html
        self.responses = list(responses)  # [(methodname, payload_or_exc)], in call order
        self.calls = []

    def get(self, url):
        return _Resp(self.my_html)

    def post(self, url, data=None, headers=None):
        payload = json.loads(data)
        assert len(payload) == 1, "moodle._run must never batch two calls in one POST"
        methodname = payload[0]["methodname"]
        self.calls.append(methodname)
        expected_name, result = self.responses[len(self.calls) - 1]
        assert methodname == expected_name
        return _Resp(json.dumps([result]))


DASHBOARD_HTML = '<script>M.cfg = {"sesskey":"sk123"};</script>'


def test_run_never_batches_courses_with_the_calendar_call_and_prefers_the_real_course_list():
    events = [CPSC101_EVENT]
    req = _FakeReq(DASHBOARD_HTML, [
        ("core_calendar_get_action_events_by_timesort", {"error": False, "data": {"events": events}}),
        ("core_enrol_get_users_courses", {"error": False, "data": [{"shortname": "CPSC101", "fullname": "Intro"}]}),
    ])
    courses, items = moodle._run(req, "https://moodle.example.edu", 0, 1)
    assert req.calls == ["core_calendar_get_action_events_by_timesort", "core_enrol_get_users_courses"]
    assert [c.code for c in courses] == ["CPSC101"]
    assert len(items) == 1


def test_run_falls_back_to_event_derived_courses_when_the_courses_call_errors():
    # Live-verified real Moodle-core behaviour (tests/live/moodle_selfhost/README.md,
    # bug #1): core_enrol_get_users_courses has no 'ajax' => true, so it always
    # errors through this endpoint. _run must still return the course the
    # calendar event itself names, not an empty list.
    events = [CPSC101_EVENT]
    req = _FakeReq(DASHBOARD_HTML, [
        ("core_calendar_get_action_events_by_timesort", {"error": False, "data": {"events": events}}),
        ("core_enrol_get_users_courses",
         {"error": True, "exception": {"message": "Web service is not available."}}),
    ])
    courses, items = moodle._run(req, "https://moodle.example.edu", 0, 1)
    assert [c.code for c in courses] == ["CPSC101"]
    assert len(items) == 1


def test_run_caps_limitnum_at_the_servers_own_maximum():
    seen = {}

    class _CapReq:
        def get(self, url):
            return _Resp(DASHBOARD_HTML)

        def post(self, url, data=None, headers=None):
            payload = json.loads(data)
            if payload[0]["methodname"] == "core_calendar_get_action_events_by_timesort":
                seen["limitnum"] = payload[0]["args"].get("limitnum")
                return _Resp(json.dumps([{"error": False, "data": {"events": []}}]))
            return _Resp(json.dumps([{"error": False, "data": []}]))

    moodle._run(_CapReq(), "https://moodle.example.edu", 0, 1)
    assert seen["limitnum"] == moodle.MAX_LIMITNUM == 50


def test_sesskey_raises_not_logged_in_when_page_has_no_sesskey():
    class _NoSessReq:
        def get(self, url):
            return _Resp("<html>please log in</html>")

    with pytest.raises(moodle.session.NotLoggedIn):
        moodle._sesskey(_NoSessReq(), "https://moodle.example.edu")


def test_sesskey_raises_not_logged_in_on_the_real_captured_login_redirect_page():
    # BRIEF finding, live-verified against a real self-hosted Moodle 4.5:
    # a logged-out /my/ 302s to /login/index.php, and that page STILL
    # renders a usable M.cfg.sesskey (its own CSRF token) - the old code
    # read that as "logged in" because extract_sesskey succeeded.
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "moodle"
            / "live_loggedout_login_page.html").read_text()
    assert moodle.extract_sesskey(html) is not None  # the trap: a sesskey really is present

    class _RespWithUrl(_Resp):
        url = "https://moodle.example.edu/login/index.php"

    class _LoginRedirectReq:
        def get(self, url):
            return _RespWithUrl(html)

    with pytest.raises(moodle.session.NotLoggedIn):
        moodle._sesskey(_LoginRedirectReq(), "https://moodle.example.edu")


def test_ajax_call_raises_runtime_error_on_a_moodle_reported_error():
    class _ErrReq:
        def post(self, url, data=None, headers=None):
            return _Resp(json.dumps([{"error": True, "exception": {"message": "boom"}}]))

    with pytest.raises(RuntimeError, match="boom"):
        moodle._ajax_call(_ErrReq(), "https://x", "sk", "some_function", {})


def test_ajax_call_raises_not_logged_in_on_servicerequireslogin():
    # BRIEF finding, live-verified: an expired session's AJAX call reports
    # error {"errorcode": "servicerequireslogin", ...}, which the old code
    # turned into a generic RuntimeError (sync recorded a stale session as
    # a bare failure, never as "re-login needed").
    class _ExpiredReq:
        def post(self, url, data=None, headers=None):
            return _Resp(json.dumps([{"error": True, "exception": {
                "message": "Web service is not available. (The session has been logged out or has expired.)",
                "errorcode": "servicerequireslogin"}}]))

    with pytest.raises(moodle.session.NotLoggedIn):
        moodle._ajax_call(_ExpiredReq(), "https://x", "sk", "core_calendar_get_action_events_by_timesort", {})


def test_calendar_events_pages_past_the_servers_limitnum_cap():
    # Unit test with two fake pages (BRIEF finding's own suggested fix).
    page_1 = [{"id": i, "name": f"e{i}", "modulename": "quiz", "timesort": 1798000000 + i,
               "url": "", "course": {"shortname": "CPSC101"}} for i in range(moodle.MAX_LIMITNUM)]
    page_2 = [{"id": 999, "name": "last", "modulename": "quiz", "timesort": 1798100000,
               "url": "", "course": {"shortname": "CPSC101"}}]
    calls = []

    class _PagedReq:
        def post(self, url, data=None, headers=None):
            args = json.loads(data)[0]["args"]
            calls.append(args.get("aftereventid"))
            page = page_1 if args.get("aftereventid") is None else page_2
            return _Resp(json.dumps([{"error": False, "data": {"events": page}}]))

    events = moodle._calendar_events(_PagedReq(), "https://moodle.example.edu", "sk", 0, 1)
    assert len(events) == moodle.MAX_LIMITNUM + 1
    assert calls == [None, moodle.MAX_LIMITNUM - 1]  # second page asked after the first page's last id


def test_calendar_events_raises_if_pagination_never_ends():
    full_page = [{"id": i, "name": "e", "modulename": "quiz", "timesort": 1798000000,
                  "url": "", "course": {}} for i in range(moodle.MAX_LIMITNUM)]

    class _NeverEndingReq:
        def post(self, url, data=None, headers=None):
            return _Resp(json.dumps([{"error": False, "data": {"events": full_page}}]))

    with pytest.raises(RuntimeError, match="pagination"):
        moodle._calendar_events(_NeverEndingReq(), "https://moodle.example.edu", "sk", 0, 1)


def test_parse_capture_rejects_wrong_source():
    with pytest.raises(ValueError, match="expected Moodle capture"):
        moodle.parse_capture({"source": "blackboard"})


def test_parse_capture_rejects_a_non_https_origin():
    with pytest.raises(ValueError, match="invalid Moodle origin"):
        moodle.parse_capture({"source": "moodle", "origin": "http://moodle.example.edu",
                               "courses": [], "events": []})


def test_parse_capture_falls_back_to_calendar_event_php_for_a_blank_url():
    capture = {
        "source": "moodle", "origin": "https://moodle.example.edu",
        "courses": [{"shortname": "CPSC101", "fullname": "Intro"}],
        "events": [CPSC101_EVENT],
    }
    courses, items = moodle.parse_capture(capture)
    assert items[0].url == "https://moodle.example.edu/calendar/event.php?id=9"


def test_parse_capture_rejects_an_event_url_on_a_foreign_origin():
    capture = {
        "source": "moodle", "origin": "https://moodle.example.edu",
        "courses": [], "events": [{**CPSC101_EVENT, "url": "https://evil.example/steal"}],
    }
    with pytest.raises(ValueError, match="unsafe"):
        moodle.parse_capture(capture)


def test_parse_capture_rejects_extra_query_params_on_the_event_url():
    capture = {
        "source": "moodle", "origin": "https://moodle.example.edu",
        "courses": [], "events": [{**CPSC101_EVENT,
                                    "url": "https://moodle.example.edu/calendar/event.php?id=9&token=abc"}],
    }
    with pytest.raises(ValueError, match="unsafe"):
        moodle.parse_capture(capture)
