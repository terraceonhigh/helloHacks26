# Workday testing: real data caught real bugs, but the fixture is fake

`hub/workday.py` and `web/lib/workday.js` were **validated against a real**
Workday "View My Courses" export (not committed, kept local), after an
earlier hand-made fixture (built from third-party reference code, before we
had a real export to check against) turned out to assume a format real
Workday never actually produces — it silently hid two real bugs that only
showed up once we tested against an actual export:

- Both `openpyxl` (`read_only=True`) and the JS `xlsx` library trust the
  sheet's declared dimension (`<dimension ref=...>`), which real Workday
  exports understate — silently truncating almost every row. Python returned
  0 courses; JS returned 1.
- Real exports have **one row per meeting component** (Lecture, Lab,
  Discussion, Studio...), each repeating the same "Course Listing" text —
  our first fixture only had one row per course, so nothing exercised
  deduping by course code.

Both are fixed in `hub/workday.py` / `web/lib/workday.js`, with regression
tests covering each (`tests/test_workday_truncated_dimension.py` /
`web/lib/workday_truncated.test.mjs` isolate the dimension bug specifically;
`tests/test_workday.py` / `web/lib/workday.test.mjs` cover the rest).

## About the fixture — corrected

An earlier version of this fixture and doc used a **real** export with only
the student's own name/number redacted. **That was wrong, and Terrace caught
it:** the export also carries **other people's data that the student can't
consent to publishing on their behalf** — real instructors' names, and a real
timetable (meeting times, buildings, rooms). A data owner can consent to
exposing their own information; they can't waive it for the instructors named
alongside it. `fixtures/workday_view_my_courses.xlsx` is now **fully
synthetic** again — made-up courses, sections, times, rooms and instructors,
matching the real structure (pre-header rows, real column layout, one row per
component) without containing anyone's real data at all.

The lesson: when a fixture is derived from a real document with more than one
person's information in it (an export, an email thread, a roster...),
redacting just the data owner's own identifiers isn't enough — check every
column/field for third parties before it goes anywhere near a public commit.

## If you want to test with your own export

Test locally against your own real file (`uv run pytest`, `npm test` pointed
at it via a temporary path override) - that's how the two bugs above were
actually found. But **don't commit a real export**, anonymised or not, since
it's very likely to carry other people's names or scheduling data alongside
yours. If your real export's structure differs from what's described above,
that's a real finding worth posting to the Agent board (#15) per rule 6, with
the specific difference described in words - not the file itself.
