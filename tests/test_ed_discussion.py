import pytest

from hub.ed_discussion import AuthError, _get_json, fetch, is_deadline_relevant, to_course, to_item

# Field names/shapes below match the real GET /api/user and
# GET /api/courses/<id>/threads responses, as read from the actual edapi
# source (smartspot2/edapi: edapi/types/api_types/{course,thread}.py,
# endpoints/{user,threads}.py) -- see hub/ed_discussion.py's module
# docstring for the exact citations. Values are fabricated/anonymised, per
# AGENTS.md rule "Fixtures must be fake or anonymised."

ACTIVE_COURSE_ENTRY = {
    "course": {
        "id": 4242,
        "realm_id": 1,
        "code": "CPSC 121",
        "name": "Models of Computation",
        "year": "2026",
        "session": "W1",
        "status": "active",
    },
    "role": {"role": "student"},
    "lab": None,
}

ARCHIVED_COURSE_ENTRY = {
    "course": {
        "id": 999,
        "realm_id": 1,
        "code": "CPSC 110",
        "name": "Computation, Programs, and Programming",
        "year": "2025",
        "session": "W2",
        "status": "archived",
    },
    "role": {"role": "student"},
    "lab": None,
}

PINNED_THREAD = {
    "id": 555001,
    "user_id": 1,
    "course_id": 4242,
    "number": 12,
    "type": "post",
    "title": "Midterm 1 room assignments",
    "content": "<document version=\"2.0\"></document>",
    "document": "<p>Room assignments are posted.</p>",
    "category": "General",
    "subcategory": "",
    "subsubcategory": "",
    "is_pinned": True,
    "is_locked": False,
    "is_answered": False,
    "created_at": "2026-09-20T12:00:00.000Z",
    "updated_at": "2026-09-20T12:00:00.000Z",
    "pinned_at": "2026-09-20T12:05:00.000Z",
}

ANNOUNCEMENT_THREAD = {
    "id": 555002,
    "user_id": 2,
    "course_id": 4242,
    "number": 13,
    "type": "announcement",
    "title": "Assignment 3 deadline extended",
    "content": "<document version=\"2.0\"></document>",
    "document": "<p>Extended to Friday.</p>",
    "category": "Announcements",
    "subcategory": "",
    "subsubcategory": "",
    "is_pinned": False,
    "is_locked": False,
    "is_answered": False,
    "created_at": "2026-09-21T09:00:00.000Z",
    "updated_at": "2026-09-21T09:00:00.000Z",
    "pinned_at": None,
}

ORDINARY_QUESTION_THREAD = {
    "id": 555003,
    "user_id": 3,
    "course_id": 4242,
    "number": 14,
    "type": "question",
    "title": "Why does my recursion not terminate?",
    "content": "<document version=\"2.0\"></document>",
    "document": "<p>Help please.</p>",
    "category": "General",
    "subcategory": "",
    "subsubcategory": "",
    "is_pinned": False,
    "is_locked": False,
    "is_answered": True,
    "created_at": "2026-09-22T09:00:00.000Z",
    "updated_at": "2026-09-22T09:00:00.000Z",
    "pinned_at": None,
}


def test_to_course_reads_real_fields():
    c = to_course(ACTIVE_COURSE_ENTRY)
    assert (c.code, c.title, c.term) == ("CPSC 121", "Models of Computation", "2026 W1")
    assert c.section == ""
    assert c.grade is None  # Ed has no grade field; never guessed at


def test_is_deadline_relevant_pinned_and_announcement_yes_ordinary_no():
    assert is_deadline_relevant(PINNED_THREAD) is True
    assert is_deadline_relevant(ANNOUNCEMENT_THREAD) is True
    assert is_deadline_relevant(ORDINARY_QUESTION_THREAD) is False


def test_to_item_is_always_undated_and_has_a_unique_url():
    i = to_item(PINNED_THREAD, "CPSC 121")
    assert i.due is None  # no due-date-shaped field exists on a real Ed thread
    assert i.category == "task"  # category_for("announcement")
    assert i.kind == "announcement"
    assert i.source == "ed_discussion"
    assert i.title == "Midterm 1 room assignments"
    assert i.url == "https://edstem.org/us/courses/4242/discussion/555001"

    j = to_item(ANNOUNCEMENT_THREAD, "CPSC 121")
    # Different threads must never collide on (source, url) - hub/db.py's
    # items table is UNIQUE(source, url); the first draft of hub/webwork.py
    # broke this exact rule.
    assert i.url != j.url


def test_to_item_url_is_unique_across_courses_via_global_thread_id():
    # thread["id"] is documented as a "global post number" - unique across
    # all of Ed, not just within one course - so even two courses' threads
    # never collide on url.
    other_course_thread = dict(PINNED_THREAD, id=999999, course_id=1)
    a = to_item(PINNED_THREAD, "CPSC 121")
    b = to_item(other_course_thread, "MATH 100")
    assert a.url != b.url


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class FakeSession:
    """Queues canned JSON responses keyed by the request path, ignoring
    query params - enough to drive fetch()'s two real endpoints
    (`user`, `courses/<id>/threads`) without hitting the network."""

    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        for path, response in self.responses.items():
            if url.endswith(path):
                return response
        raise AssertionError(f"unexpected request: {url}")


def test_fetch_skips_archived_courses_and_keeps_only_deadline_relevant_items(monkeypatch):
    fake = FakeSession({
        "user": FakeResponse(200, {"courses": [ACTIVE_COURSE_ENTRY, ARCHIVED_COURSE_ENTRY]}),
        "courses/4242/threads": FakeResponse(200, {
            "threads": [PINNED_THREAD, ANNOUNCEMENT_THREAD, ORDINARY_QUESTION_THREAD]
        }),
    })
    monkeypatch.setattr("hub.ed_discussion.requests.Session", lambda: fake)

    courses, items = fetch("fake-token")

    assert [c.code for c in courses] == ["CPSC 121"]  # archived course dropped
    assert fake.headers["Authorization"] == "Bearer fake-token"
    assert {i.title for i in items} == {
        "Midterm 1 room assignments",
        "Assignment 3 deadline extended",
    }  # the ordinary question thread never becomes an Item
    assert all(i.due is None for i in items)


def test_fetch_returns_empty_on_bad_token(monkeypatch):
    fake = FakeSession({"user": FakeResponse(401, {"code": "bad_token"})})
    monkeypatch.setattr("hub.ed_discussion.requests.Session", lambda: fake)

    assert fetch("bad-token") == ([], [])


def test_get_json_raises_auth_error_on_401():
    fake = FakeSession({"user": FakeResponse(401, {})})
    with pytest.raises(AuthError):
        _get_json(fake, "user")
