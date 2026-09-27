# Regression oracle for e3db118: real Workday exports declare a truncated
# <dimension ref=...>, and a reader that trusts it (openpyxl read_only=True)
# silently drops rows. The fixture's dimension is A1:A1 but it has 8 rows.
from hub.workday import parse_workday_courses

FIXTURE = "fixtures/workday_truncated_dimension.xlsx"


def test_truncated_dimension_still_parses_every_row():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert [c.code for c in courses] == ["FAKE 101", "FAKE 202", "FAKE 303", "FAKE 404"]


def test_truncated_dimension_last_row_fields():
    courses = parse_workday_courses(FIXTURE, term="2026W1")
    assert courses[-1].title == "Last Row Standing"
    assert courses[-1].term == "2026W1"
