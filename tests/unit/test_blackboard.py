"""Unit tests for lauds.adapters.blackboard. main has no dedicated
tests/test_blackboard.py (module docstring: no live Blackboard tenant
anywhere on this project) - these port the module's own documented
behaviour (pagination, missing-term tolerance, capture validation) rather
than a specific main test file."""
import json

import pytest

from lauds.adapters import blackboard
from lauds.models import Course

COURSE = {"courseId": "BIOL101", "id": "_1_1", "name": "Biology", "term": {"name": "Fall 2026"}}


def test_to_course_prefers_the_human_readable_courseid():
    c = blackboard.to_course(COURSE)
    assert isinstance(c, Course)
    assert c.code == "BIOL101"
    assert c.title == "Biology"
    assert c.term == "Fall 2026"
    assert c.section == ""
    assert c.source == "blackboard"


def test_to_course_falls_back_to_internal_id_when_courseid_is_absent():
    c = blackboard.to_course({"id": "_2_1", "name": "No Code"})
    assert c.code == "_2_1"


def test_to_course_leaves_term_blank_when_expand_term_is_not_honoured():
    c = blackboard.to_course({"courseId": "MATH200", "name": "Calculus"})
    assert c.term == ""


def test_next_page_returns_the_documented_nextpage_path():
    page = {"results": [], "paging": {"nextPage": "/learn/api/public/v1/users/me/courses?offset=10"}}
    assert blackboard.next_page(page) == "/learn/api/public/v1/users/me/courses?offset=10"


def test_next_page_is_none_once_there_isnt_one():
    assert blackboard.next_page({"results": []}) is None


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.ok = status < 400

    def text(self):
        return json.dumps(self._payload)


class _FakeRequest:
    def __init__(self, by_url):
        self.by_url = by_url
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.by_url[url]


def test_fetch_follows_pagination_and_expands_each_course(monkeypatch):
    base = "https://bb.example.edu"
    by_url = {
        f"{base}/learn/api/public/v1/users/me": _Resp({"id": "u1"}),
        f"{base}/learn/api/public/v1/users/u1/courses": _Resp({
            "results": [{"courseId": "BIOL101"}],
            "paging": {"nextPage": "/learn/api/public/v1/users/u1/courses?offset=1"},
        }),
        f"{base}/learn/api/public/v1/users/u1/courses?offset=1": _Resp({
            "results": [{"courseId": "MATH200"}],
        }),
        f"{base}/learn/api/public/v1/courses/BIOL101?expand=term": _Resp(COURSE),
        f"{base}/learn/api/public/v1/courses/MATH200?expand=term": _Resp(
            {"courseId": "MATH200", "name": "Calculus"}),
    }
    req = _FakeRequest(by_url)
    monkeypatch.setattr(blackboard.session, "fetch_with_session",
                         lambda site_name, base_, run: run(req))
    bundle = blackboard.fetch(base)
    assert [c.code for c in bundle.courses] == ["BIOL101", "MATH200"]
    assert bundle.items == []
    assert any(u.endswith("offset=1") for u in req.calls)


def test_fetch_skips_a_membership_row_with_no_courseid_rather_than_guess(monkeypatch):
    base = "https://bb.example.edu"
    by_url = {
        f"{base}/learn/api/public/v1/users/me": _Resp({"id": "u1"}),
        f"{base}/learn/api/public/v1/users/u1/courses": _Resp({"results": [{"bogus": True}]}),
    }
    req = _FakeRequest(by_url)
    monkeypatch.setattr(blackboard.session, "fetch_with_session",
                         lambda site_name, base_, run: run(req))
    bundle = blackboard.fetch(base)
    assert bundle.courses == []


def test_get_json_raises_not_logged_in_on_401(monkeypatch):
    req = _FakeRequest({"https://bb.example.edu/x": _Resp({}, status=401)})
    with pytest.raises(blackboard.session.NotLoggedIn):
        blackboard._get_json(req, "https://bb.example.edu", "/x")


def test_parse_capture_maps_courses_and_never_invents_items():
    capture = {"source": "blackboard", "courses": [COURSE]}
    courses, items = blackboard.parse_capture(capture)
    assert [c.code for c in courses] == ["BIOL101"]
    assert items == []


def test_parse_capture_rejects_wrong_source():
    with pytest.raises(ValueError, match="expected Blackboard capture"):
        blackboard.parse_capture({"source": "moodle", "courses": []})


def test_parse_capture_rejects_a_non_dict_course_row():
    with pytest.raises(ValueError, match="invalid Blackboard capture"):
        blackboard.parse_capture({"source": "blackboard", "courses": ["not a dict"]})


def test_parse_capture_rejects_an_oversized_course_list():
    with pytest.raises(ValueError, match="invalid Blackboard capture"):
        blackboard.parse_capture({"source": "blackboard", "courses": [COURSE] * 101})
