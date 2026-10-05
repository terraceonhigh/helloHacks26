import pytest

from hub import captures


def test_capture_dispatch_uses_existing_canvas_model_mapper():
    courses, items = captures.parse({
        "source": "canvas",
        "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [{"course_id": 7, "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z",
                     "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3"}],
        "undated": [],
    })
    assert [c.code for c in courses] == ["CPSC 121"]
    assert [(i.source, i.kind, i.course) for i in items] == [
        ("canvas", "quiz", "CPSC 121")
    ]


def test_normalize_returns_json_safe_identity_deduped_shared_rows():
    planner = {"course_id": 7, "plannable_type": "quiz",
               "plannable_date": "2026-09-30T06:59:00Z",
               "plannable": {"title": "Quiz 2"},
               "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3"}
    result = captures.normalize({
        "source": "canvas", "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [planner, planner], "undated": []})
    assert result["stored"] is False
    assert len(result["items"]) == 1
    assert result["items"][0]["due"] == "2026-09-30T06:59:00+00:00"
    assert result["courses"][0]["code"] == "CPSC 121"


def test_completed_extension_capture_normalizes_to_done_for_canvas_and_prairielearn():
    canvas = captures.normalize({
        "source": "canvas", "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [{"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
                     "plannable": {"title": "Quiz 2"}, "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                     "submissions": {"submitted": True, "excused": False},
                     "planner_override": {"marked_complete": False}}], "undated": []})
    assert canvas["items"][0]["done"] is True

    prairielearn = captures.normalize({
        "source": "prairielearn", "origin": "https://us.prairielearn.com",
        "courses": [{"ci_id": "221053", "title": "CPSC 317: Internet Computing, 2026 Winter Term 1",
                     "assessments": [{"title": "Quiz 2", "group": "Quizzes",
                                      "href": "/pl/course_instance/221053/assessment_instance/14835025/",
                                      "due_text": "", "score_text": "100%", "credit_empty": False}]}]})
    assert prairielearn["items"][0]["done"] is True


@pytest.mark.parametrize("capture", [None, [], {"source": "../db"},
                                            {"source": "missing_provider"}, {"source": "site"}])
def test_capture_dispatch_rejects_unverified_sources(capture):
    with pytest.raises(ValueError):
        captures.parse(capture)
