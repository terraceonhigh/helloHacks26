"""Behaviour tests for lauds.adapters.piazza. Main (hub/piazza.py) has no
dedicated tests/test_piazza.py - the only oracle-backed coverage is its
module docstring's cited real-source behaviours plus one
tests/test_experimental_captures.py case (ported as parity, see
tests/parity/test_piazza.py). These are that same behaviour, exercised
directly rather than only through a golden."""
import pytest

from lauds import session
from lauds.adapters import piazza
from lauds.models import Bundle


def test_to_course_prefers_course_number_over_name():
    c = piazza.to_course({"course_number": "CPSC 121", "name": "Models", "term": "Fall 2026", "id": "abc"})
    assert c.code == "CPSC 121" and c.title == "Models" and c.section == "" and c.source == "piazza"


def test_to_course_falls_back_to_name_when_course_number_absent():
    # ponytail noted in to_course: course_number is genuinely absent on some
    # real classes (piazza-api's own .get(..., '') ) - falls back to name.
    c = piazza.to_course({"name": "Some Class", "id": "def"})
    assert c.code == "Some Class" and c.term == ""


@pytest.mark.parametrize("post", [
    {"tags": ["pin"]},
    {"tags": ["instructor-note"]},
    {"bucket_name": "Pinned"},
    {"tags": ["pin", "instructor-note"], "bucket_name": "Pinned"},
])
def test_to_item_surfaces_pinned_or_instructor_posts(post):
    item = piazza.to_item({**post, "id": "p1", "history": [{"subject": "Room change"}]}, "CPSC 121", "nid1")
    assert item is not None
    assert item.title == "Room change"
    assert item.kind == "announcement" and item.category == "task"
    assert item.due is None  # no due-date field exists anywhere in scope
    assert item.url == "https://piazza.com/class/nid1?cid=p1"
    assert item.source == "piazza"


@pytest.mark.parametrize("post", [{"tags": []}, {"bucket_name": "Today"}, {}])
def test_to_item_drops_ordinary_posts(post):
    assert piazza.to_item({**post, "id": "p2"}, "CPSC 121") is None


def test_to_item_falls_back_to_untitled_when_history_is_empty():
    item = piazza.to_item({"tags": ["pin"], "id": "p3", "history": []}, "CPSC 121")
    assert item.title == "(untitled post)"


def test_to_item_honors_capitalised_history_fallback():
    # [unverified] casing, per the module docstring - checked as a fallback.
    item = piazza.to_item({"tags": ["pin"], "id": "p4", "History": [{"subject": "Capitalised"}]}, "CPSC 121")
    assert item.title == "Capitalised"


def test_parse_capture_rejects_wrong_source():
    with pytest.raises(ValueError):
        piazza.parse_capture({"source": "canvas", "networks": []})


def test_parse_capture_rejects_too_many_networks():
    with pytest.raises(ValueError):
        piazza.parse_capture({"source": "piazza", "networks": [{"id": "a", "posts": []}] * 101})


def test_parse_capture_rejects_a_non_alnum_network_id():
    with pytest.raises(ValueError):
        piazza.parse_capture({"source": "piazza", "networks": [{"id": "not alnum!", "posts": []}]})


def test_parse_capture_rejects_too_many_posts():
    posts = [{"id": f"p{i}", "tags": []} for i in range(piazza.DEFAULT_POST_LIMIT + 1)]
    with pytest.raises(ValueError):
        piazza.parse_capture({"source": "piazza", "networks": [{"id": "abc", "posts": posts}]})


def test_parse_capture_rejects_a_non_alnum_post_id():
    with pytest.raises(ValueError):
        piazza.parse_capture({"source": "piazza", "networks": [{"id": "abc", "posts": [{"id": "not alnum!"}]}]})


def test_parse_capture_drops_ordinary_posts_but_keeps_the_course():
    bundle = piazza.parse_capture({"source": "piazza", "networks": [{
        "id": "abc123", "name": "Some Class",
        "posts": [{"id": "postX", "tags": [], "history": [{"subject": "Just a question"}]}],
    }]})
    assert [c.code for c in bundle.courses] == ["Some Class"]
    assert bundle.items == []


def test_login_delegates_to_shared_session_login(monkeypatch):
    calls = []
    monkeypatch.setattr(session, "login", lambda site, base, **kw: calls.append((site, base, kw)))
    piazza.login(headless=True)
    assert calls == [("piazza", "https://piazza.com", {"headless": True})]


def test_fetch_never_raises_on_failure(monkeypatch):
    def boom(site, base, run):
        raise RuntimeError("no session / network down / whatever")

    monkeypatch.setattr(session, "fetch_with_session", boom)
    assert piazza.fetch() == Bundle()


def test_fetch_returns_what_run_produces(monkeypatch):
    sentinel = Bundle(courses=[piazza.to_course({"name": "X", "id": "1"})])
    monkeypatch.setattr(session, "fetch_with_session", lambda site, base, run: sentinel)
    assert piazza.fetch() is sentinel


class _FakeResp:
    def __init__(self, body, ok=True):
        self._body = body
        self.ok = ok

    def json(self):
        return self._body


class _FakeReq:
    """Records every POST; a canned reply per RPC method name."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def post(self, url, data, headers):
        import json as _json

        body = _json.loads(data)
        self.calls.append((url, body))
        return _FakeResp({"result": self.replies[body["method"]]})


def test_run_fetches_every_network_and_skips_a_network_missing_an_id():
    req = _FakeReq({
        "user.status": {"networks": [{"id": "n1", "name": "A", "course_number": "CPSC 121"},
                                      {"name": "B - no id, skipped"}]},
        "network.get_my_feed": {"feed": [{"id": "post1"}]},
        "content.get": {"id": "post1", "tags": ["pin"], "history": [{"subject": "Hello"}]},
    })
    bundle = piazza._run(req, limit=piazza.DEFAULT_POST_LIMIT)
    assert [c.code for c in bundle.courses] == ["CPSC 121", "B - no id, skipped"]
    assert len(bundle.items) == 1 and bundle.items[0].course == "CPSC 121"


def test_run_lets_a_not_logged_in_error_propagate_for_a_retry():
    class _ExpiredReq:
        def post(self, url, data, headers):
            return _FakeResp({}, ok=False)  # non-OK -> session.NotLoggedIn per _call

    with pytest.raises(session.NotLoggedIn):
        piazza._run(_ExpiredReq(), limit=10)


def test_run_continues_past_one_networks_failure():
    calls = {"n": 0}

    class _FlakyReq:
        def post(self, url, data, headers):
            import json as _json

            body = _json.loads(data)
            if body["method"] == "user.status":
                return _FakeResp({"result": {"networks": [{"id": "bad", "name": "Bad"},
                                                            {"id": "good", "name": "Good"}]}})
            if body["method"] == "network.get_my_feed":
                calls["n"] += 1
                if body["params"]["nid"] == "bad":
                    raise RuntimeError("malformed response")
                return _FakeResp({"result": {"feed": []}})
            raise AssertionError("unexpected call")

    bundle = piazza._run(_FlakyReq(), limit=10)
    assert calls["n"] == 2  # both networks were tried
    assert {c.code for c in bundle.courses} == {"Bad", "Good"}
