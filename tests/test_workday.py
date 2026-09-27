from hub.workday import parse_workday_courses

# Fully synthetic (fake student, courses, instructors, timetable) - matches
# the real export's structure (pre-header rows, real column layout, one row
# per meeting component) without containing anyone's real data. See
# docs/workday-testing.md.
FIXTURE = "fixtures/workday_view_my_courses.xlsx"


def test_parses_all_unique_course_rows():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert [c.code for c in courses] == ["BMEG 000", "BMEG 001", "BMEG 002"]


def test_fields_from_first_row():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    bmeg000 = courses[0]
    assert bmeg000.term == "2026W1"
    assert bmeg000.title == "Fake Thermodynamics"
    # Real Workday "Course Listing" text never embeds a section number (it
    # lives in a separate column this parser doesn't read) - always None.
    assert bmeg000.section is None


def test_duplicate_component_rows_dedupe_to_one_course():
    # Real exports have one row per meeting component (Lecture, Lab,
    # Discussion...), each repeating the same Course Listing text. BMEG 000
    # has 2 rows (Lecture + Laboratory) in this fixture.
    codes = [c.code for c in parse_workday_courses(FIXTURE, term="2026W1")]
    assert codes.count("BMEG 000") == 1


def test_no_separator_falls_back_to_raw_listing_as_title():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    bmeg002 = courses[2]
    assert bmeg002.title == "bmeg002"
