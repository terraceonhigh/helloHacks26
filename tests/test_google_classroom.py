"""Tests against fixtures built directly from Google's own documented
response shapes (see hub/google_classroom.py's module docstring for the
citations - Course, CourseWork, StudentSubmission field shapes, and the
SubmissionState enum values). No network in these tests."""
from datetime import timezone

from hub.google_classroom import (
    _done_from_state,
    _due,
    _url,
    done_map_from_submissions,
    fetch,
    to_course,
    to_item,
)


def test_to_course():
    # Course resource fields per
    # https://developers.google.com/workspace/classroom/reference/rest/v1/courses
    c = to_course({"id": "1234", "name": "CPSC 121 101", "section": "101",
                   "courseState": "ACTIVE"})
    assert (c.code, c.section, c.term, c.title, c.grade) == ("CPSC 121 101", "101", "", "CPSC 121 101", None)


def test_due_with_date_and_time():
    # dueDate = google.type.Date (year/month/day), dueTime = google.type.TimeOfDay
    # (hours/minutes/seconds/nanos), documented as UTC - see module docstring.
    work = {"dueDate": {"year": 2026, "month": 9, "day": 30}, "dueTime": {"hours": 23, "minutes": 59}}
    due = _due(work)
    assert (due.year, due.month, due.day, due.hour, due.minute) == (2026, 9, 30, 23, 59)
    assert due.tzinfo is timezone.utc


def test_due_missing_is_none():
    assert _due({}) is None
    assert _due({"dueDate": None}) is None


def test_due_date_without_time_defaults_midnight_utc():
    due = _due({"dueDate": {"year": 2026, "month": 10, "day": 1}})
    assert (due.hour, due.minute, due.tzinfo) == (0, 0, timezone.utc)


def test_url_prefers_alternate_link():
    work = {"alternateLink": "https://classroom.google.com/c/abc/a/def/details",
            "courseId": "abc", "id": "def"}
    assert _url(work) == "https://classroom.google.com/c/abc/a/def/details"


def test_url_falls_back_to_course_and_work_id_when_no_alternate_link():
    # Real historical bug in this repo (hub/webwork.py's first draft): two
    # items both getting url="" collided on hub.db's UNIQUE(source, url).
    # A DRAFT courseWork item may have no alternateLink yet, so this must
    # never fall back to "".
    a = _url({"courseId": "course-1", "id": "work-1"})
    b = _url({"courseId": "course-1", "id": "work-2"})
    assert a and b and a != b


def test_to_item_maps_kind_category_and_done():
    work = {"id": "w1", "title": "Problem Set 1", "workType": "ASSIGNMENT",
            "alternateLink": "https://classroom.google.com/c/1/a/w1/details",
            "dueDate": {"year": 2026, "month": 10, "day": 5}, "dueTime": {"hours": 8}}
    item = to_item(work, "CPSC 121 101", {"w1": True})
    assert (item.course, item.kind, item.category, item.title, item.done, item.source) == (
        "CPSC 121 101", "assignment", "task", "Problem Set 1", True, "google_classroom")
    assert item.due.hour == 8


def test_to_item_unknown_worktype_defaults_to_assignment():
    item = to_item({"id": "w2", "title": "Untitled"}, "CPSC 121", {})
    assert item.kind == "assignment"
    assert item.done is None  # no matching submission -> unknown, not False


# SubmissionState enum values, cited:
# https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions#SubmissionState
def test_done_from_state_turned_in_and_returned_are_done():
    assert _done_from_state("TURNED_IN") is True
    assert _done_from_state("RETURNED") is True


def test_done_from_state_created_and_reclaimed_are_not_done():
    assert _done_from_state("CREATED") is False
    assert _done_from_state("RECLAIMED_BY_STUDENT") is False


def test_done_from_state_ambiguous_states_are_unknown():
    # STUDENT_EDITED_AFTER_TURN_IN is genuinely ambiguous (see module
    # docstring) - unknown, not a guessed True/False.
    assert _done_from_state("STUDENT_EDITED_AFTER_TURN_IN") is None
    assert _done_from_state("STATE_UNSPECIFIED") is None
    assert _done_from_state(None) is None


def test_done_map_from_submissions():
    subs = [
        {"courseWorkId": "w1", "state": "TURNED_IN"},
        {"courseWorkId": "w2", "state": "CREATED"},
        {"id": "no-course-work-id-field"},  # malformed/partial row: must not crash or get a None key
    ]
    assert done_map_from_submissions(subs) == {"w1": True, "w2": False}


def test_fetch_with_no_saved_token_returns_empty(tmp_path, monkeypatch):
    # No ~/.ubc-hub/google_classroom-token.json -> nothing to do, same
    # "unavailable" contract every other adapter follows (AGENTS.md).
    import hub.google_classroom as gc

    monkeypatch.setattr(gc, "token_path", lambda: tmp_path / "google_classroom-token.json")
    assert fetch() == ([], [])


def test_fetch_returns_empty_on_a_broken_token_file(tmp_path, monkeypatch):
    import hub.google_classroom as gc

    path = tmp_path / "google_classroom-token.json"
    path.write_text("not json")
    monkeypatch.setattr(gc, "token_path", lambda: path)
    assert fetch() == ([], [])
