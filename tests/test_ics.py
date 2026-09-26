from datetime import date, datetime
from pathlib import Path

from hub.ics import parse_ics

FEED = (Path(__file__).parent.parent / "fixtures" / "canvas_calendar.ics").read_text()


def test_parses_all_events():
    items = parse_ics(FEED)
    assert len(items) == 5


def test_pulls_course_tag_out_of_summary():
    items = parse_ics(FEED)
    ps2 = next(i for i in items if i.title == "Problem Set 2")
    assert ps2.course_key == "CPSC 110 101"


def test_event_with_no_course_tag_has_none_course_key():
    items = parse_ics(FEED)
    study_group = next(i for i in items if "Study group" in i.title)
    assert study_group.course_key is None


def test_kind_guessing():
    items = parse_ics(FEED)
    by_title = {i.title: i for i in items}
    assert by_title["Problem Set 2"].kind == "assignment"
    assert by_title["Midterm 1"].kind == "exam"
    assert by_title["Pre-lecture quiz 5"].kind == "quiz"
    assert by_title["Study group (no course tag)"].kind == "event"


def test_datetime_event_due_is_timezone_aware():
    items = parse_ics(FEED)
    ps2 = next(i for i in items if i.title == "Problem Set 2")
    assert isinstance(ps2.due, datetime)
    assert ps2.due.tzinfo is not None


def test_all_day_event_due_is_a_plain_date():
    items = parse_ics(FEED)
    quiz = next(i for i in items if i.title == "Pre-lecture quiz 5")
    assert isinstance(quiz.due, date)
    assert not isinstance(quiz.due, datetime)


def test_source_and_url_and_id():
    items = parse_ics(FEED)
    ps2 = next(i for i in items if i.title == "Problem Set 2")
    assert ps2.source == "ics"
    assert ps2.url == "https://canvas.ubc.ca/courses/1/assignments/1001"
    assert ps2.id == "ics:event:event-assignment-1001@canvas.instructure.com"
