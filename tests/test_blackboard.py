"""Tests for hub/blackboard.py.

**[unverified]** Every JSON fixture below is constructed from Blackboard's
own public REST API documentation (developer.blackboard.com /
docs.blackboard.com/rest-apis/learn) for the Users, Course Memberships,
Courses and Term resources -- NOT captured from a live instance. No
Blackboard tenant exists anywhere on this project (UBC runs Canvas, plus one
Brightspace course per hub/brightspace.py). See hub/blackboard.py's module
docstring and docs/api-standards.md's Blackboard detail section for exactly
what's a documented fact vs. an unverified hypothesis here. These tests only
confirm the parsers do what this module's own documented-shape assumptions
say they should -- they are not, and cannot be, evidence that a real
Blackboard tenant responds this way.
"""
from hub import blackboard
from hub.blackboard import _get_all, _get_json, next_page, to_course

# [unverified] Shape of the Courses resource per Blackboard's docs: the
# human-readable `courseId` (distinct from the internal `id` used in the
# URL), a `name` title, and a `term` object nested in by `?expand=term`.
COURSE_JSON = {
    "id": "_12345_1",
    "courseId": "BIOL101.2026FA",
    "name": "Introduction to Biology",
    "term": {"id": "_9_1", "name": "2026 Fall Term"},
}

# [unverified] Same shape without a `term` (either the tenant doesn't honour
# `expand=term`, or the course simply has none) - must not crash, just leave
# `term` blank, same as hub/brightspace.py's own "no separate field" gap.
COURSE_JSON_NO_TERM = {
    "id": "_67890_1",
    "courseId": "CPSC121.2026FA",
    "name": "Models of Computation",
}

# [unverified] A malformed/edge-case row: no human-readable courseId at all.
COURSE_JSON_NO_COURSE_ID = {
    "id": "_11111_1",
    "name": "Some Course With No Code",
}

# [unverified] Blackboard's documented list-response paging shape.
PAGE_WITH_NEXT = {
    "results": [{"courseId": "1"}],
    "paging": {"nextPage": "/learn/api/public/v1/users/_1_1/courses?offset=1"},
}
PAGE_WITHOUT_NEXT = {"results": [{"courseId": "2"}]}
PAGE_WITH_EMPTY_PAGING = {"results": [{"courseId": "3"}], "paging": {}}


def test_to_course_reads_code_title_and_expanded_term():
    c = to_course(COURSE_JSON)
    assert (c.code, c.title, c.term) == ("BIOL101.2026FA", "Introduction to Biology", "2026 Fall Term")
    assert c.section == ""  # no documented per-membership section field


def test_to_course_leaves_term_blank_when_not_expanded():
    c = to_course(COURSE_JSON_NO_TERM)
    assert c.term == ""
    assert c.code == "CPSC121.2026FA"


def test_to_course_falls_back_to_internal_id_when_no_human_code():
    # ponytail-equivalent: the documented shape isn't guaranteed on every
    # tenant, so a missing courseId must not crash the adapter.
    c = to_course(COURSE_JSON_NO_COURSE_ID)
    assert c.code == "_11111_1"


def test_next_page_returns_documented_paging_field():
    assert next_page(PAGE_WITH_NEXT) == "/learn/api/public/v1/users/_1_1/courses?offset=1"


def test_next_page_none_when_no_paging_object():
    assert next_page(PAGE_WITHOUT_NEXT) is None


def test_next_page_none_when_paging_object_has_no_next_page():
    assert next_page(PAGE_WITH_EMPTY_PAGING) is None


# ---------------------------------------------------------------------------
# Orchestration (_get_json, _get_all, fetch): the parser-level tests above
# check to_course/next_page, but not the glue that builds requests, follows
# pagination, and degrades on failure -- that's exactly where real,
# separate bugs have been found and fixed for the other new connectors this
# session (a broken doubled-up URL in hub/brightspace.py, a password-in-URL
# in hub/moodle.py). Covering it here too, plus a defensive fix: _get_json
# no longer blindly concatenates base+path if `path` ever turns out to be a
# full absolute URL rather than the documented relative one.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, json_body, status=200, ok=True):
        self._json = json_body
        self.status = status
        self.ok = ok

    def json(self):
        return self._json


def test_get_json_builds_the_right_url_for_a_relative_path():
    seen = {}

    class FakeReq:
        def get(self, url):
            seen["url"] = url
            return _FakeResponse({"ok": True})

    _get_json(FakeReq(), "https://blackboard.example.edu", "/learn/api/public/v1/users/me")
    assert seen["url"] == "https://blackboard.example.edu/learn/api/public/v1/users/me"


def test_get_json_does_not_double_up_when_path_is_already_a_full_url():
    # The defensive fix: if paging.nextPage (or any caller) ever hands back
    # an absolute URL instead of the documented relative path, don't glue
    # base onto the front of it too.
    seen = {}

    class FakeReq:
        def get(self, url):
            seen["url"] = url
            return _FakeResponse({"ok": True})

    full_url = "https://blackboard.example.edu/learn/api/public/v1/users/_1_1/courses?offset=1"
    _get_json(FakeReq(), "https://blackboard.example.edu", full_url)
    assert seen["url"] == full_url  # not "https://blackboard.example.eduhttps://..."


def test_get_json_raises_not_logged_in_on_401():
    from hub import site

    class FakeReq:
        def get(self, url):
            return _FakeResponse(None, status=401, ok=False)

    try:
        _get_json(FakeReq(), "https://blackboard.example.edu", "/x")
        assert False, "expected NotLoggedIn"
    except site.NotLoggedIn:
        pass


def test_get_all_follows_pagination_to_the_end():
    class FakeReq:
        def __init__(self):
            self.calls = 0

        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                return _FakeResponse(PAGE_WITH_NEXT)
            return _FakeResponse(PAGE_WITHOUT_NEXT)

    req = FakeReq()
    results = _get_all(req, "https://blackboard.example.edu", "/learn/api/public/v1/users/_1_1/courses")
    assert [r["courseId"] for r in results] == ["1", "2"]
    assert req.calls == 2


def test_fetch_degrades_to_empty_lists_on_any_failure(monkeypatch):
    def fake_fetch_with_session(site_name, base, run):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(blackboard.site, "fetch_with_session", fake_fetch_with_session)
    assert blackboard.fetch("https://blackboard.example.edu") == ([], [])


def test_fetch_wires_me_id_into_the_course_memberships_call(monkeypatch):
    seen_paths = []

    class FakeReq:
        def get(self, url):
            seen_paths.append(url)
            if url.endswith("/users/me"):
                return _FakeResponse({"id": "_42_1"})
            if "courses" in url and "?expand=term" not in url:
                return _FakeResponse({"results": [{"courseId": "BIOL101.2026FA"}]})
            return _FakeResponse(COURSE_JSON)

    def fake_fetch_with_session(site_name, base, run):
        return run(FakeReq())

    monkeypatch.setattr(blackboard.site, "fetch_with_session", fake_fetch_with_session)
    courses, items = blackboard.fetch("https://blackboard.example.edu")

    assert any("_42_1" in p for p in seen_paths)  # me["id"] actually flowed into the next call
    assert courses[0].code == "BIOL101.2026FA"
    assert items == []
