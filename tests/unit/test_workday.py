"""Behaviour ported from main's tests/test_workday*.py (not literal copies -
same scenarios, run through lauds.adapters.workday's pure functions on raw
bytes instead of a file path). Reuses the same fixtures the offline harvest
already committed under tests/fixtures/workday/."""
import io
import signal
from datetime import date, time
from pathlib import Path

import openpyxl
import pytest

from lauds.adapters.workday import parse_courses, parse_schedule

FIXTURES = Path(__file__).parent.parent / "fixtures" / "workday"


def _bytes(name):
    return (FIXTURES / name).read_bytes()


def _one_row_xlsx(meeting_pattern="2026-09-08 - 2026-12-05 | Mon Wed Fri | 10:00 a.m. - 11:00 a.m. | Room 1",
                   instructional_format="Lecture"):
    """Same shape as main's test helper, but built straight into memory - no
    tmp_path file needed since our parser takes raw bytes, not a path."""
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Instructional Format", "Meeting Patterns"])
    sheet.append(["BMEG 000 - Fake Thermodynamics", instructional_format, meeting_pattern])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- parse_courses -----------------------------------------------------------


def test_parses_all_unique_course_rows():
    courses = parse_courses(_bytes("view_my_courses.xlsx"), term="2026W1")
    assert [c.code for c in courses] == ["BMEG 000", "BMEG 001", "BMEG 002"]


def test_fields_from_first_row():
    bmeg000 = parse_courses(_bytes("view_my_courses.xlsx"), term="2026W1")[0]
    assert bmeg000.term == "2026W1"
    assert bmeg000.title == "Fake Thermodynamics"
    # Real Workday "Course Listing" text never embeds a section number (it
    # lives in a separate column this parser doesn't read) - always None.
    assert bmeg000.section is None


def test_duplicate_component_rows_dedupe_to_one_course():
    # BMEG 000 has 2 rows (Lecture + Laboratory) in this fixture.
    codes = [c.code for c in parse_courses(_bytes("view_my_courses.xlsx"), term="2026W1")]
    assert codes.count("BMEG 000") == 1


def test_no_separator_falls_back_to_raw_listing_as_title():
    courses = parse_courses(_bytes("view_my_courses.xlsx"), term="2026W1")
    assert courses[2].title == "bmeg002"


def test_truncated_dimension_still_parses_every_row():
    # Regression for e3db118: the file's declared <dimension ref> understates
    # the real range (A1:A1, but 8 rows exist).
    courses = parse_courses(_bytes("truncated_dimension.xlsx"), term="2026W1")
    assert [c.code for c in courses] == ["FAKE 101", "FAKE 202", "FAKE 303", "FAKE 404"]
    assert courses[-1].title == "Last Row Standing"


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="SIGALRM is Unix-only")
def test_stray_cell_at_max_address_parses_quickly():
    # Regression for #49 item 13: a stray populated cell at Excel's max
    # address (XFD1048576) made a naive read materialise the full 1M x 16K
    # grid and hang for over a minute.
    def _fail_on_hang(signum, frame):
        raise TimeoutError("parse_courses hung on a stray far-away cell")

    previous = signal.signal(signal.SIGALRM, _fail_on_hang)
    signal.alarm(20)
    try:
        courses = parse_courses(_bytes("stray_cell.xlsx"), term="2026W1")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert [c.code for c in courses] == ["BMEG 000", "BMEG 001", "BMEG 002"]


# --- parse_schedule -----------------------------------------------------------


def test_one_meeting_per_component_row():
    # Unlike parse_courses, which dedupes to one Course, each component row
    # keeps its own Meeting.
    meetings = parse_schedule(_bytes("view_my_courses.xlsx"), term="2026W1")
    assert [(m.course, m.kind) for m in meetings] == [
        ("BMEG 000", "lecture"), ("BMEG 000", "lab"), ("BMEG 001", "lecture"), ("BMEG 002", "lecture"),
    ]


def test_fields_from_first_meeting():
    m = parse_schedule(_bytes("view_my_courses.xlsx"), term="2026W1")[0]
    assert m.days == ["MO", "WE", "FR"]
    assert m.start_time == time(10, 0)
    assert m.end_time == time(11, 0)
    assert m.term_start == date(2026, 9, 8)
    assert m.term_end == date(2026, 12, 5)
    assert m.location == "Fake Building (FAKE), Floor: 1, Room: 100"
    assert m.source == "workday"


@pytest.mark.parametrize("format_text,expected", [
    ("Lecture", "lecture"), ("Laboratory", "lab"), ("Seminar", "seminar"),
    ("Tutorial", "tutorial"), ("Discussion", "tutorial"), ("Exam", "exam"),
    ("Something Unseen", "class"),
])
def test_kind_for_every_known_instructional_format(format_text, expected):
    meetings = parse_schedule(_one_row_xlsx(instructional_format=format_text), term="2026W1")
    assert meetings[0].kind == expected


def test_a_line_with_no_recognizable_days_is_skipped_not_guessed():
    raw = _one_row_xlsx(meeting_pattern="2026-09-08 - 2026-12-05 | TBD | 10:00 a.m. - 11:00 a.m. | Room 1")
    assert parse_schedule(raw, term="2026W1") == []


def test_an_unparseable_time_is_skipped_not_guessed():
    raw = _one_row_xlsx(meeting_pattern="2026-09-08 - 2026-12-05 | Mon Wed Fri | TBD | Room 1")
    assert parse_schedule(raw, term="2026W1") == []


def test_a_bare_dash_meeting_pattern_produces_no_meetings():
    # A bare "-" is an async/online component with no fixed time - not
    # enough to build a Meeting, shouldn't crash either.
    assert parse_schedule(_one_row_xlsx(meeting_pattern="-"), term="2026W1") == []


def test_multiple_meeting_lines_in_one_cell_all_parse():
    # A lecture with two distinct weekly slots shows up as two
    # newline-separated lines in the same cell.
    pattern = (
        "2026-09-08 - 2026-12-05 | Mon Wed | 10:00 a.m. - 11:00 a.m. | Room 1\n"
        "2026-09-08 - 2026-12-05 | Fri | 09:00 a.m. - 10:00 a.m. | Room 2"
    )
    meetings = parse_schedule(_one_row_xlsx(meeting_pattern=pattern), term="2026W1")
    assert len(meetings) == 2
    assert meetings[0].days == ["MO", "WE"]
    assert meetings[1].days == ["FR"]
    assert meetings[1].location == "Room 2"


def test_an_export_with_no_meeting_patterns_column_returns_no_meetings():
    # An older export, or one from a school whose Workday config doesn't
    # expose this column - degrade to [], same contract as a header
    # parse_courses can't find.
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Section"])
    sheet.append(["BMEG 000 - Fake Thermodynamics", "101"])
    buf = io.BytesIO()
    wb.save(buf)
    assert parse_schedule(buf.getvalue(), term="2026W1") == []


def test_fetch_reads_a_path_and_returns_both(tmp_path):
    from lauds.adapters.workday import fetch
    path = tmp_path / "export.xlsx"
    path.write_bytes(_bytes("view_my_courses.xlsx"))
    bundle = fetch(path, term="2026W1")
    assert len(bundle.courses) == 3
    assert len(bundle.meetings) == 4
