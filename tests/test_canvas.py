from hub.canvas import done_from_submissions, to_course, to_item, unwrap


def test_unwrap_strips_guard():
    assert unwrap('while(1);[{"id": 1}]') == [{"id": 1}]
    assert unwrap('[]') == []


def test_mapping():
    c = to_course({"id": 7, "course_code": "CPSC 121", "name": "Models of Computation",
                   "term": {"name": "2026W1"}, "enrollments": [{"computed_current_score": 88.5}]})
    assert (c.code, c.term, c.grade) == ("CPSC 121", "2026W1", 88.5)
    i = to_item({"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
                 "plannable": {"title": "Quiz 2"}, "html_url": "/courses/7/quizzes/3"}, {7: "CPSC 121"})
    assert (i.course, i.category, i.kind, i.title, i.due.day) == ("CPSC 121", "deadline", "quiz", "Quiz 2", 30)
    assert i.url == "https://canvas.ubc.ca/courses/7/quizzes/3"
    event = to_item({"plannable_type": "calendar_event", "plannable": {}}, {})
    assert (event.kind, event.category) == ("event", "deadline")
    assignment = to_item({"plannable_type": "discussion_topic", "plannable": {}}, {})
    assert (assignment.kind, assignment.category) == ("assignment", "task")


def test_done_from_submissions():
    # Real shapes seen from planner/items: a dict for anything gradeable,
    # a bare `false` for announcements/events - nothing to report there.
    assert done_from_submissions({"submissions": {"submitted": True, "excused": False}}) is True
    assert done_from_submissions({"submissions": {"submitted": False, "excused": True}}) is True
    assert done_from_submissions({"submissions": {"submitted": False, "excused": False}}) is False
    assert done_from_submissions({"submissions": False}) is None
    assert done_from_submissions({}) is None
