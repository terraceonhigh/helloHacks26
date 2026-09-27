# Regression oracle for #49 item 13 (the Python twin of item 3, fixed in
# web/lib/workday.js by #57): a stray populated cell at Excel's max address
# (XFD1048576) made parse_workday_courses() materialise the full 1M x 16K
# grid and hang for over a minute. Built from the fake fixture at test time,
# so no extra binary is committed.
import signal

import openpyxl
import pytest

from hub.workday import parse_workday_courses

FIXTURE = "fixtures/workday_view_my_courses.xlsx"


@pytest.fixture
def stray_cell_xlsx(tmp_path):
    workbook = openpyxl.load_workbook(FIXTURE)
    workbook.active["XFD1048576"] = "stray"
    out = tmp_path / "stray_cell.xlsx"
    workbook.save(out)
    return out


def _fail_on_hang(signum, frame):
    raise TimeoutError("parse_workday_courses hung on a stray far-away cell")


def test_stray_cell_at_max_address_parses_quickly(stray_cell_xlsx):
    previous = signal.signal(signal.SIGALRM, _fail_on_hang)
    signal.alarm(20)
    try:
        courses = parse_workday_courses(stray_cell_xlsx, term="2026W1")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert [c.code for c in courses] == ["BMEG 000", "BMEG 001", "BMEG 002"]
