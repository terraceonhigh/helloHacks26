from hub.workday import parse_workday_courses

FIXTURE = "fixtures/workday_view_my_courses.xlsx"


def test_parses_all_course_rows():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert [c.code for c in courses] == ["FAKE 100", "FAKE 200", "FAKE 300"]


def test_fields_from_first_row():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    fake100 = courses[0]
    assert fake100.term == "2026W1"
    assert fake100.title == "Introduction to Fake Studies"
    # Real Workday "Course Listing" text never embeds a section number (it
    # lives in a separate column this parser doesn't read) - always None.
    assert fake100.section is None


def test_duplicate_component_rows_dedupe_to_one_course():
    # Real exports have one row per meeting component (Lecture, Lab,
    # Discussion...), each repeating the same Course Listing text.
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert [c.code for c in courses].count("FAKE 100") == 1


def test_no_separator_falls_back_to_raw_listing_as_title():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    fake300 = courses[2]
    assert fake300.title == "fake300"
