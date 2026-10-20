"""Tests for hub/piazza.py's recent-activity adapter (Item/to_post/
recent_posts). Every fixture is SYNTHETIC, built from the real field names
cited in hub/piazza.py's own module docstring (the piazza-api source and its
Piazza_API_Post_Data_Dictionary.md) - not captured from a live Piazza
network, matching this project's [unverified] caveat for every other
untested adapter.
"""
import json

from hub import piazza, site
from hub.models import Course, Item
from hub.piazza import _canonical_course_code, recent_posts, to_course, to_post

NETWORK = {
    "name": "Models of Computation",
    "term": "Fall 2026",
    "course_number": "CPSC121",
    "id": "hl5qm84dl4t3x2",
    "prof_hash": ["uid_abc"],
}
OTHER_NETWORK = {
    "name": "MATH 200 Discussion",
    "term": "Fall 2026",
    "id": "az9qm84dl4t3x9",
    "prof_hash": [],
}

ORDINARY_POST = {
    "id": "kz1ghi890j",
    "folders": ["hw1"],
    "created": "2026-10-03T15:00:00Z",
    "type": "question",
    "bucket_name": "Today",
    "tags": ["student", "unanswered"],
    "history": [{
        "subject": "Question about Q3",
        "created": "2026-10-03T15:00:00Z",
        "content": "<p>Is <b>part (b)</b> asking for a proof or just an example?</p>",
    }],
}
PINNED_POST = {
    "id": "kz1abc234d",
    "folders": ["exam"],
    "created": "2026-10-01T12:00:00Z",
    "type": "note",
    "bucket_name": "Pinned",
    "tags": ["pin", "instructor-note", "exam"],
    "history": [{
        "subject": "Midterm 1 room assignments",
        "created": "2026-10-01T12:00:00Z",
        "content": "Room bookings are up on the course website.",
    }],
}
POST_WITH_NO_HISTORY = {"id": "kz1nohist", "tags": [], "created": "2026-09-30T00:00:00Z", "bucket_name": "Today"}


def test_canonical_course_code_collapses_to_the_shared_dbs_form():
    # "CPSC121" (no space) -> "CPSC 121" - the same canonical form
    # hub.db._canonical_code uses, so a Piazza-only post lines up with the
    # same course card Canvas/Workday built ("associate that with our data").
    assert to_course(NETWORK).code == "CPSC 121"


def test_canonical_course_code_parses_a_number_even_with_trailing_words():
    # normalise_course_code matches faculty+number and ignores the rest -
    # "MATH 200 Discussion" still canonicalises to "MATH 200", the same
    # shortened form hub.db._canonical_code would produce.
    assert to_course(OTHER_NETWORK).code == "MATH 200"


def test_canonical_course_code_falls_back_when_it_doesnt_parse_at_all():
    unparseable = Course(code="???", section="", term="", title="")
    assert _canonical_course_code(unparseable.code) == "???"


def test_to_post_includes_ordinary_non_pinned_posts():
    # The real difference from to_item(): to_post() doesn't filter by
    # pinned/instructor status at all - "most recent messages" wants
    # ordinary class activity too.
    post = to_post(ORDINARY_POST, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert isinstance(post, Item)
    assert (post.course, post.title) == ("CPSC 121", "Question about Q3")
    assert post.kind == "post"
    assert post.due is None
    assert post.source == "piazza"
    assert "kz1ghi890j" in post.url


def test_to_post_missing_title_falls_back_rather_than_crashing():
    post = to_post(POST_WITH_NO_HISTORY, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert post.title == "(untitled post)"


class _FakeResponse:
    def __init__(self, body, ok=True):
        self._body = body
        self.ok = ok

    def json(self):
        return self._body


def _rpc_result(result):
    return _FakeResponse({"result": result})


def test_recent_posts_merges_and_sorts_most_recent_first_across_classes(monkeypatch):
    class FakeReq:
        def post(self, url, data, headers):
            body = json.loads(data)
            method, params = body["method"], body["params"]
            if method == "user.status":
                return _rpc_result({"networks": [NETWORK, OTHER_NETWORK]})
            if method == "network.get_my_feed" and params["nid"] == NETWORK["id"]:
                return _rpc_result({"feed": [{"id": PINNED_POST["id"]}]})
            if method == "network.get_my_feed" and params["nid"] == OTHER_NETWORK["id"]:
                return _rpc_result({"feed": [{"id": ORDINARY_POST["id"]}]})
            if method == "content.get" and params["cid"] == PINNED_POST["id"]:
                return _rpc_result(PINNED_POST)
            if method == "content.get" and params["cid"] == ORDINARY_POST["id"]:
                return _rpc_result(ORDINARY_POST)
            raise AssertionError(f"unexpected call: {method} {params}")

    def fake_fetch_with_session(site_name, base, run):
        return run(FakeReq())

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)

    posts = recent_posts(limit=10)
    # ORDINARY_POST (2026-10-03) is more recent than PINNED_POST (2026-10-01)
    # even though it's from a different class and isn't pinned at all.
    assert [p.title for p in posts] == ["Question about Q3", "Midterm 1 room assignments"]
    assert [p.course for p in posts] == ["MATH 200", "CPSC 121"]


def test_recent_posts_skips_one_broken_class_but_keeps_the_rest(monkeypatch):
    class FakeReq:
        def post(self, url, data, headers):
            body = json.loads(data)
            method, params = body["method"], body["params"]
            if method == "user.status":
                return _rpc_result({"networks": [NETWORK, OTHER_NETWORK]})
            if method == "network.get_my_feed" and params["nid"] == OTHER_NETWORK["id"]:
                raise RuntimeError("simulated malformed response for this one class")
            if method == "network.get_my_feed":
                return _rpc_result({"feed": [{"id": PINNED_POST["id"]}]})
            if method == "content.get":
                return _rpc_result(PINNED_POST)
            raise AssertionError(f"unexpected call: {method} {params}")

    def fake_fetch_with_session(site_name, base, run):
        return run(FakeReq())

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)

    posts = recent_posts(limit=10)
    assert [p.title for p in posts] == ["Midterm 1 room assignments"]


def test_recent_posts_caps_the_merged_result_to_limit(monkeypatch):
    many_posts = [
        {"id": f"p{i}", "created": f"2026-10-0{i}T00:00:00Z", "tags": [],
         "history": [{"subject": f"Post {i}", "content": f"Body {i}"}]}
        for i in range(1, 6)
    ]

    class FakeReq:
        def post(self, url, data, headers):
            body = json.loads(data)
            method, params = body["method"], body["params"]
            if method == "user.status":
                return _rpc_result({"networks": [NETWORK]})
            if method == "network.get_my_feed":
                # Real Piazza sorts a feed by "updated" (most recent first,
                # per the real params cited in _posts_for_network) - fake it
                # the same way, newest id first, so slicing to `limit` here
                # behaves like the real API would.
                return _rpc_result({"feed": [{"id": p["id"]} for p in reversed(many_posts)]})
            if method == "content.get":
                return _rpc_result(next(p for p in many_posts if p["id"] == params["cid"]))
            raise AssertionError(f"unexpected call: {method} {params}")

    def fake_fetch_with_session(site_name, base, run):
        return run(FakeReq())

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)

    posts = recent_posts(limit=3)
    assert [p.title for p in posts] == ["Post 5", "Post 4", "Post 3"]


def test_recent_posts_returns_empty_on_total_failure(monkeypatch):
    def fake_fetch_with_session(site_name, base, run):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)
    assert recent_posts() == []


def test_recent_posts_lets_not_logged_in_propagate_for_fetch_with_sessions_own_retry(monkeypatch):
    # NotLoggedIn is the one exception the per-class loop must NOT swallow -
    # hub.site.fetch_with_session catches it at the top level to retry the
    # whole call once after a fresh login, same as every other adapter.
    class FakeReq:
        def post(self, url, data, headers):
            return _FakeResponse({}, ok=False)

    seen = []

    def fake_fetch_with_session(site_name, base, run):
        seen.append(1)
        try:
            run(FakeReq())
        except site.NotLoggedIn:
            seen.append("caught")
        return [], []

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)
    recent_posts()
    assert seen == [1, "caught"]


def _mock_posts(monkeypatch, posts, networks=None):
    calls = []

    def call(req, method, data=None, nid=None):
        calls.append((method, data))
        if method == "user.status":
            return {"networks": networks if networks is not None else [NETWORK]}
        if method == "network.get_my_feed":
            return {"feed": [{"id": post["id"]} for post in posts]}
        return next(post for post in posts if post["id"] == data["cid"])

    monkeypatch.setattr(piazza, "_call", call)
    monkeypatch.setattr(site, "fetch_with_session", lambda name, base, run: run(None))
    return calls


def test_recent_order_compares_instants_not_iso_strings(monkeypatch):
    posts = [
        {**ORDINARY_POST, "id": "offset", "created": "2026-10-03T16:00:00+02:00"},
        {**ORDINARY_POST, "id": "utc", "created": "2026-10-03T15:00:00Z"},
        {**ORDINARY_POST, "id": "fraction", "created": "2026-10-03T15:00:00.100+00:00"},
        {**ORDINARY_POST, "id": "invalid", "created": "unknown"},
        {**ORDINARY_POST, "id": "naive", "created": "2026-10-04T15:00:00"},
        {**ORDINARY_POST, "id": "missing", "created": None},
    ]
    _mock_posts(monkeypatch, posts)
    result = recent_posts()
    assert [p.url.split("cid=")[1] for p in result] == [
        "fraction", "utc", "offset", "invalid", "naive", "missing"]
    assert all(p.due is None for p in result)


def test_fetch_recent_items_persist_through_shared_db(monkeypatch):
    from hub import db

    _mock_posts(monkeypatch, [ORDINARY_POST, PINNED_POST])
    courses, items = piazza.fetch(include_recent=True)
    assert {c.code for c in courses} == {i.course for i in items} == {"CPSC 121"}
    assert [i.kind for i in items] == ["post", "announcement"]
    conn = db.connect(":memory:")
    try:
        db.save(conn, courses, items)
        db.save(conn, courses, items)
        assert len(db.undated(conn)) == 2  # repeated fetch upserts, never duplicates
        assert len(db.courses(conn)) == 1
    finally:
        conn.close()


def test_default_fetch_keeps_announcement_only_contract(monkeypatch):
    _mock_posts(monkeypatch, [ORDINARY_POST, PINNED_POST])
    courses, items = piazza.fetch()
    assert [i.kind for i in items] == ["announcement"]
    assert items[0].course == courses[0].code == "CPSC 121"


def test_capture_uses_same_course_codes_as_fetch(monkeypatch):
    _mock_posts(monkeypatch, [PINNED_POST])
    courses, items = piazza.fetch()
    captured_courses, captured_items = piazza.parse_capture({
        "source": "piazza", "networks": [{**NETWORK, "posts": [PINNED_POST]}]})
    assert captured_courses == courses
    assert captured_items == items


def test_malformed_class_and_post_do_not_discard_good_items(monkeypatch):
    _mock_posts(monkeypatch, [
        {**ORDINARY_POST, "id": "bad", "history": [None]}, PINNED_POST,
    ], networks=[None, {**NETWORK, "course_number": 42}, NETWORK])
    assert [i.title for i in recent_posts()] == ["Midterm 1 room assignments"]


def test_limit_is_bounded_and_nonpositive_skips_login(monkeypatch):
    calls = _mock_posts(monkeypatch, [ORDINARY_POST])
    assert recent_posts(0) == []
    assert recent_posts(-1) == []
    assert calls == []
    recent_posts(10000)
    assert next(data["limit"] for method, data in calls if method == "network.get_my_feed") == piazza.DEFAULT_POST_LIMIT


def test_missing_post_identity_is_not_persistable():
    assert to_post({"history": [{"subject": "No ID"}]}, "CPSC121", NETWORK["id"]) is None
    assert to_post(ORDINARY_POST, "CPSC121") is None


def test_post_auth_failure_reaches_session_retry(monkeypatch):
    import pytest

    def call(req, method, data=None, nid=None):
        if method == "user.status":
            return {"networks": [NETWORK]}
        if method == "network.get_my_feed":
            return {"feed": [{"id": "expired"}]}
        raise site.NotLoggedIn

    seen = []

    def session(name, base, run):
        with pytest.raises(site.NotLoggedIn):
            run(None)
        seen.append("retry")
        return [], []

    monkeypatch.setattr(piazza, "_call", call)
    monkeypatch.setattr(site, "fetch_with_session", session)
    assert recent_posts() == []
    assert seen == ["retry"]
