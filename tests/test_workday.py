from hub.workday import _course_from_listing, parse_workday_courses

# A real "View My Courses" export (name/student number replaced with a
# placeholder in column A; every other column, including every real course,
# is unmodified - see docs/workday-testing.md).
FIXTURE = "fixtures/workday_view_my_courses.xlsx"

EXPECTED_CODES = [
    "BMEG 210", "BMEG 245", "APSC 160", "MECH 260", "BMEG 257",
    "BMEG 201", "ANTH 100", "AMNE 151", "BMEG 230",
]


def test_parses_all_unique_course_rows():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert [c.code for c in courses] == EXPECTED_CODES


def test_fields_from_first_row():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    bmeg210 = courses[0]
    assert bmeg210.term == "2026W1"
    assert bmeg210.title == "Thermodynamics in Biomedical Engineering"
    # Real Workday "Course Listing" text never embeds a section number (it
    # lives in a separate column this parser doesn't read) - always None.
    assert bmeg210.section is None


def test_duplicate_component_rows_dedupe_to_one_course():
    # Real exports have one row per meeting component (Lecture, Lab,
    # Discussion...), each repeating the same Course Listing text. BMEG 210
    # has 2 rows (Lecture + Discussion) and BMEG 230 has 3 in this export.
    codes = [c.code for c in parse_workday_courses(FIXTURE, term="2026W1")]
    assert codes.count("BMEG 210") == 1
    assert codes.count("BMEG 230") == 1


def test_no_separator_falls_back_to_raw_listing_as_title():
    # Doesn't occur in the real export (every real listing has " - "), so
    # this exercises the fallback directly rather than via a fixture.
    course = _course_from_listing("FOO101", "2026W1")
    assert course.code == "FOO 101"
    assert course.title == "FOO101"
