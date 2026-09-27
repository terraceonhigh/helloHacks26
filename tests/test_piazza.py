"""Tests for hub/piazza.py's recent-activity sidebar feed (Post/to_post/
recent_posts). Every fixture is SYNTHETIC, built from the real field names
cited in hub/piazza.py's own module docstring (the piazza-api source and its
Piazza_API_Post_Data_Dictionary.md) - not captured from a live Piazza
network, matching this project's [unverified] caveat for every other
untested adapter.
"""
import json

from hub import piazza, site
from hub.models import Course
from hub.piazza import Post, _canonical_course_code, _post_text, recent_posts, to_course, to_post

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
    assert _canonical_course_code(to_course(NETWORK)) == "CPSC 121"


def test_canonical_course_code_parses_a_number_even_with_trailing_words():
    # normalise_course_code matches faculty+number and ignores the rest -
    # "MATH 200 Discussion" still canonicalises to "MATH 200", the same
    # shortened form hub.db._canonical_code would produce.
    assert _canonical_course_code(to_course(OTHER_NETWORK)) == "MATH 200"


def test_canonical_course_code_falls_back_when_it_doesnt_parse_at_all():
    unparseable = Course(code="???", section="", term="", title="")
    assert _canonical_course_code(unparseable) == "???"


def test_post_text_strips_html_from_the_real_content_field():
    assert _post_text(ORDINARY_POST) == "Is part (b) asking for a proof or just an example?"


def test_post_text_empty_when_no_history_at_all():
    assert _post_text(POST_WITH_NO_HISTORY) == ""


def test_to_post_includes_ordinary_non_pinned_posts():
    # The real difference from to_item(): to_post() doesn't filter by
    # pinned/instructor status at all - "most recent messages" wants
    # ordinary class activity too.
    post = to_post(ORDINARY_POST, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert isinstance(post, Post)
    assert (post.course, post.title) == ("CPSC 121", "Question about Q3")
    assert post.text == "Is part (b) asking for a proof or just an example?"
    assert post.created == "2026-10-03T15:00:00Z"
    assert "kz1ghi890j" in post.url


def test_to_post_missing_title_falls_back_rather_than_crashing():
    post = to_post(POST_WITH_NO_HISTORY, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert post.title == "(untitled post)"
    assert post.text == ""


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
        return []

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)
    recent_posts()
    assert seen == [1, "caught"]
