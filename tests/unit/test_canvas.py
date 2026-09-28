"""Behavioural port of main's tests/test_canvas.py, against lauds.adapters.canvas.

Not ported: test_oauth_fetch_reuses_the_canvas_mapping_without_local_browser,
test_oauth_token_cannot_follow_a_foreign_pagination_link (partially - kept
below as test_bearer_token_cannot_follow_a_foreign_pagination_link),
test_canvas_oauth_authorization_and_token_grants,
test_canvas_oauth_error_does_not_echo_upstream_secrets - all exercise the
server-side OAuth authorization-code exchange this adapter drops (see the
module docstring: that flow was the hosted/Vercel product's, thrown out per
BRIEF.md). A personal-access-token fetch is kept and tested here instead.
"""
import pytest

from lauds.adapters import canvas


def test_unwrap_strips_guard():
    assert canvas.unwrap('while(1);[{"id": 1}]') == [{"id": 1}]
    assert canvas.unwrap("[]") == []


def test_mapping():
    c = canvas.to_course({"id": 7, "course_code": "CPSC 121", "name": "Models of Computation",
                          "term": {"name": "2026W1"}, "enrollments": [{"computed_current_score": 88.5}]})
    assert (c.code, c.term, c.grade) == ("CPSC 121", "2026W1", 88.5)
    i = canvas.to_item({"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
                        "plannable": {"title": "Quiz 2"}, "html_url": "/courses/7/quizzes/3"}, {7: "CPSC 121"})
    assert (i.course, i.category, i.kind, i.title, i.due.day) == ("CPSC 121", "deadline", "quiz", "Quiz 2", 30)
    assert i.url == "https://canvas.ubc.ca/courses/7/quizzes/3"
    event = canvas.to_item({"plannable_type": "calendar_event", "plannable": {}}, {})
    assert (event.kind, event.category) == ("event", "deadline")
    assignment = canvas.to_item({"plannable_type": "discussion_topic", "plannable": {}}, {})
    assert (assignment.kind, assignment.category) == ("assignment", "task")


def test_calendar_event_url_is_not_double_prefixed():
    event = canvas.to_item({"plannable_type": "calendar_event",
                            "plannable": {"title": "Office hours"},
                            "html_url": "https://canvas.ubc.ca/calendar?event_id=9"}, {})
    assert event.url == "https://canvas.ubc.ca/calendar?event_id=9"


def test_to_undated_item():
    a = {"name": "Reading response", "html_url": "/courses/7/assignments/9",
         "has_submitted_submissions": True}
    i = canvas.to_undated_item(a, "CPSC 121")
    assert (i.course, i.kind, i.category, i.title, i.due, i.done) == (
        "CPSC 121", "assignment", "task", "Reading response", None, True)
    assert i.url == "https://canvas.ubc.ca/courses/7/assignments/9"


def test_announcement_has_no_due_date():
    announcement = canvas.to_item({"plannable_type": "announcement", "plannable_date": "2026-01-05T12:00:00Z",
                                   "plannable": {"title": "Welcome!"}, "html_url": "/courses/7/announcements/1"}, {})
    assert announcement.due is None
    assert announcement.category == "task"


def test_done_from_submissions():
    assert canvas.done_from_submissions({"submissions": {"submitted": True, "excused": False}}) is True
    assert canvas.done_from_submissions({"submissions": {"submitted": False, "excused": True}}) is True
    assert canvas.done_from_submissions({"submissions": {"submitted": False, "excused": False}}) is False
    assert canvas.done_from_submissions({"submissions": False}) is None
    assert canvas.done_from_submissions({}) is None


def test_done_from_submissions_also_honors_the_manual_complete_checkbox():
    assert canvas.done_from_submissions({"submissions": False, "planner_override": {"marked_complete": True}}) is True
    assert canvas.done_from_submissions({"planner_override": {"marked_complete": True}}) is True
    assert canvas.done_from_submissions(
        {"submissions": {"submitted": False}, "planner_override": {"marked_complete": False}}) is False
    assert canvas.done_from_submissions({"planner_override": None}) is None


def test_points_and_description_are_captured_additively():
    # lauds additions (not in main): compat.to_main drops both, so parity
    # never sees them, but the CLI can still show a point value or a
    # description when Canvas's own JSON has one.
    i = canvas.to_item({"plannable_type": "assignment",
                        "plannable": {"title": "Essay", "points_possible": 10.0, "description": "<p>Write it</p>"}}, {})
    assert (i.points, i.description) == (10.0, "<p>Write it</p>")


def test_fetch_with_access_token_reuses_the_canvas_mapping_without_local_browser(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def __init__(self, body):
            import json
            self.text = json.dumps(body)

    class Session:
        def __init__(self):
            self.headers = {}
            self.paths = []

        def get(self, url, *, timeout, allow_redirects):
            from urllib.parse import urlparse
            assert self.headers == {"Authorization": "Bearer fake-access-token"}
            assert timeout == 15 and allow_redirects is False
            path = urlparse(url).path
            self.paths.append(path)
            if path == "/api/v1/courses":
                return Response([{"id": 7, "course_code": "CPSC 121", "name": "Models"}])
            if path == "/api/v1/planner/items":
                return Response([{"course_id": 7, "plannable_type": "quiz",
                                  "plannable_date": "2026-09-30T06:59:00Z",
                                  "plannable": {"title": "Quiz 2"},
                                  "html_url": "/courses/7/quizzes/3"}])
            if path == "/api/v1/courses/7/assignments":
                return Response([{"name": "Reading response", "due_at": None,
                                  "html_url": "/courses/7/assignments/9"}])
            raise AssertionError(url)

    session = Session()
    import requests
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(canvas.session, "fetch_with_session", lambda *_a, **_k: pytest.fail("local browser used"))
    bundle = canvas.fetch(access_token="fake-access-token")
    assert [c.code for c in bundle.courses] == ["CPSC 121"]
    assert [(i.kind, i.course, i.title) for i in bundle.items] == [
        ("quiz", "CPSC 121", "Quiz 2"),
        ("assignment", "CPSC 121", "Reading response"),
    ]
    assert session.paths == ["/api/v1/courses", "/api/v1/planner/items",
                             "/api/v1/courses/7/assignments"]


def test_bearer_token_cannot_follow_a_foreign_pagination_link():
    with pytest.raises(ValueError, match="allowed origin"):
        canvas._TokenRequest("fake-token").get("https://attacker.example/api/v1/courses")


def test_empty_access_token_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        canvas._TokenRequest("")


def test_extension_capture_uses_the_same_canvas_model_mapping():
    capture = {
        "source": "canvas",
        "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [{"course_id": 7, "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z",
                     "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                     "submissions": {"submitted": True}}],
        "undated": [{"course_id": 7, "name": "Reading", "due_at": None,
                     "html_url": "https://canvas.ubc.ca/courses/7/assignments/9",
                     "has_submitted_submissions": False}],
    }
    bundle = canvas.parse_capture(capture)
    assert [c.code for c in bundle.courses] == ["CPSC 121"]
    assert [(i.course, i.kind, i.done) for i in bundle.items] == [
        ("CPSC 121", "quiz", True), ("CPSC 121", "assignment", False)
    ]
    capture["planner"][0]["html_url"] = "https://evil.example/steal"
    with pytest.raises(ValueError, match="invalid item"):
        canvas.parse_capture(capture)
    capture["planner"][0]["html_url"] = "https://canvas.ubc.ca/courses/7/quizzes/3?access_token=fake"
    with pytest.raises(ValueError, match="invalid item"):
        canvas.parse_capture(capture)


def test_parse_capture_rejects_a_non_canvas_source():
    with pytest.raises(ValueError, match="expected a Canvas capture"):
        canvas.parse_capture({"source": "moodle", "courses": [], "planner": [], "undated": []})


def test_parse_capture_rejects_an_oversized_capture():
    with pytest.raises(ValueError, match="invalid Canvas capture"):
        canvas.parse_capture({"source": "canvas", "courses": [{}] * 101, "planner": [], "undated": []})
