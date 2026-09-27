import openpyxl

from hub.logic import normalise_course_code
from hub.models import Course

_SHEET_NAME = "View My Courses"
_COURSE_HEADER_ALIASES = {"course listing", "course"}
# Zero-based ceilings, same values as web/lib/workday.js's MAX_SANE_ROW/COL.
# A real export is a few hundred rows; these only bound pathological files.
_MAX_SANE_ROW = 10_000
_MAX_SANE_COL = 500


def _find_header_row(rows):
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            value = str(cell).strip().lower() if cell is not None else ""
            if value in _COURSE_HEADER_ALIASES:
                return row_index, col_index
    return None, None


def _course_from_listing(listing, term):
    code_part, _, title = listing.partition(" - ")
    faculty, number, section = normalise_course_code(code_part)
    if not faculty or not number:
        return None

    return Course(
        code=f"{faculty} {number}",
        section=section,
        term=term,
        title=title.strip() or listing,
    )


def _read_rows(path):
    # Two real-export hazards, handled together (#49):
    # - the declared <dimension> understates the populated range, so a
    #   read_only sheet that trusts it silently truncates. reset_dimensions()
    #   drops the declared range and streams the cells actually present.
    # - a stray cell at Excel's max address (XFD1048576) made read_only=False
    #   iter_rows() materialise the full 1M x 16K grid (>60s, >2GB).
    #   Streaming + the same sane ceilings web/lib/workday.js uses keep it
    #   bounded.
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[_SHEET_NAME] if _SHEET_NAME in workbook.sheetnames else workbook.active
        sheet.reset_dimensions()
        return [row[:_MAX_SANE_COL + 1] for row in sheet.iter_rows(max_row=_MAX_SANE_ROW + 1, values_only=True)]
    finally:
        workbook.close()


def parse_workday_courses(path, term):
    rows = _read_rows(path)

    header_row_index, course_col = _find_header_row(rows)
    if header_row_index is None:
        return []

    # Real exports have one row per meeting component (Lecture, Lab,
    # Discussion...), each repeating the same course listing text - dedupe
    # by code, keeping the first occurrence.
    courses = []
    seen_codes = set()
    for row in rows[header_row_index + 1:]:
        if course_col >= len(row) or not row[course_col]:
            continue
        course = _course_from_listing(str(row[course_col]).strip(), term)
        if course is not None and course.code not in seen_codes:
            seen_codes.add(course.code)
            courses.append(course)
    return courses
