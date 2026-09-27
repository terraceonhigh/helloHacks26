"""Regenerate fixtures/workday_truncated_dimension.xlsx (fake data only).

Real Workday "View My Courses" exports declare a sheet dimension that
understates the populated range (e.g. <dimension ref="A1:A1"/>), so any reader
that trusts it (openpyxl read_only=True, SheetJS !ref) silently drops rows.
This writes a normal workbook, then rewrites the dimension to A1:A1.
No duplicate component rows, so a failure here isolates the truncation bug
from the (separate) dedupe fix.

    uv run python fixtures/make_workday_truncated_dimension.py
"""
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import openpyxl

OUT = Path(__file__).with_name("workday_truncated_dimension.xlsx")
HEADER = ["", "Course Listing", "Credits", "Section", "Instructional Format"]
ROWS = [
    ["", "FAKE 101 - Truncation Studies I", 3, "FAKE 101-001", "Lecture"],
    ["", "FAKE 202 - Hidden Rows", 3, "FAKE 202-001", "Lecture"],
    ["", "FAKE 303 - Undercounted Ranges", 3, "FAKE 303-001", "Lecture"],
    ["", "FAKE 404 - Last Row Standing", 3, "FAKE 404-001", "Lecture"],
]


def main():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "View My Courses"
    ws.append(["My Enrolled Courses"])
    ws.append([None, None, None, "Enrolled Sections"])
    ws.append(HEADER)
    for row in ROWS:
        ws.append(row)
    with tempfile.TemporaryDirectory() as tmp:
        plain = Path(tmp) / "plain.xlsx"
        wb.save(plain)
        with zipfile.ZipFile(plain) as src, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "xl/worksheets/sheet1.xml":
                    data, n = re.subn(rb'<dimension ref="[^"]*"', b'<dimension ref="A1:A1"', data)
                    assert n == 1, "dimension element not found"
                dst.writestr(info, data)


if __name__ == "__main__":
    main()
