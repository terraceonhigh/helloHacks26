from datetime import date, time

import openpyxl
import pytest

from hub.workday import parse_workday_schedule

FIXTURE = "fixtures/workday_view_my_courses.xlsx"


def test_one_meeting_per_component_row():
    # BMEG 000 has 2 rows (Lecture + Laboratory) - unlike parse_workday_courses,
    # which dedupes to one Course, each component keeps its own Meeting.
    meetings = parse_workday_schedule(FIXTURE, term="2026W1")
    assert [(m.course, m.kind) for m in meetings] == [
        ("BMEG 000", "lecture"),
        ("BMEG 000", "lab"),
        ("BMEG 001", "lecture"),
        ("BMEG 002", "lecture"),
    ]


def test_fields_from_first_row():
    m = parse_workday_schedule(FIXTURE, term="2026W1")[0]
    assert m.days == ["MO", "WE", "FR"]
    assert m.start_time == time(10, 0)
    assert m.end_time == time(11, 0)
    assert m.term_start == date(2026, 9, 8)
    assert m.term_end == date(2026, 12, 5)
    assert m.location == "Fake Building (FAKE), Floor: 1, Room: 100"
    assert m.source == "workday"


def _one_row_workbook(path, meeting_pattern="2026-09-08 - 2026-12-05 | Mon Wed Fri | 10:00 a.m. - 11:00 a.m. | Room 1",
                       instructional_format="Lecture"):
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Instructional Format", "Meeting Patterns"])
    sheet.append(["BMEG 000 - Fake Thermodynamics", instructional_format, meeting_pattern])
    wb.save(path)
    return path


@pytest.mark.parametrize("format_text,expected", [
    ("Lecture", "lecture"), ("Laboratory", "lab"), ("Seminar", "seminar"),
    ("Tutorial", "tutorial"), ("Discussion", "tutorial"), ("Exam", "exam"),
    ("Something Unseen", "class"),
])
def test_kind_for_every_known_instructional_format(tmp_path, format_text, expected):
    path = _one_row_workbook(tmp_path / "one_row.xlsx", instructional_format=format_text)
    meetings = parse_workday_schedule(path, term="2026W1")
    assert meetings[0].kind == expected


def test_a_line_with_no_recognizable_days_is_skipped_not_guessed(tmp_path):
    path = _one_row_workbook(tmp_path / "one_row.xlsx",
                              meeting_pattern="2026-09-08 - 2026-12-05 | TBD | 10:00 a.m. - 11:00 a.m. | Room 1")
    assert parse_workday_schedule(path, term="2026W1") == []


def test_an_unparseable_time_is_skipped_not_guessed(tmp_path):
    path = _one_row_workbook(tmp_path / "one_row.xlsx",
                              meeting_pattern="2026-09-08 - 2026-12-05 | Mon Wed Fri | TBD | Room 1")
    assert parse_workday_schedule(path, term="2026W1") == []


def test_a_bare_dash_meeting_pattern_produces_no_meetings(tmp_path):
    # Real exports use a bare "-" for an async/online component with no
    # fixed time - not enough to build a meeting, shouldn't crash either.
    path = _one_row_workbook(tmp_path / "one_row.xlsx", meeting_pattern="-")
    assert parse_workday_schedule(path, term="2026W1") == []


def test_multiple_meeting_lines_in_one_cell_all_parse(tmp_path):
    # A lecture with two distinct weekly slots (e.g. Mon/Wed one time, Fri
    # another) shows up as two newline-separated lines in the same cell.
    pattern = (
        "2026-09-08 - 2026-12-05 | Mon Wed | 10:00 a.m. - 11:00 a.m. | Room 1\n"
        "2026-09-08 - 2026-12-05 | Fri | 09:00 a.m. - 10:00 a.m. | Room 2"
    )
    path = _one_row_workbook(tmp_path / "one_row.xlsx", meeting_pattern=pattern)
    meetings = parse_workday_schedule(path, term="2026W1")
    assert len(meetings) == 2
    assert meetings[0].days == ["MO", "WE"]
    assert meetings[1].days == ["FR"]
    assert meetings[1].location == "Room 2"


def test_an_export_with_no_meeting_patterns_column_returns_no_meetings(tmp_path):
    # An older export, or one from a school whose Workday config doesn't
    # expose this column - degrade to [], same contract as
    # parse_workday_courses on a header it can't find.
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Section"])
    sheet.append(["BMEG 000 - Fake Thermodynamics", "101"])
    path = tmp_path / "no_meeting_patterns.xlsx"
    wb.save(path)
    assert parse_workday_schedule(path, term="2026W1") == []
