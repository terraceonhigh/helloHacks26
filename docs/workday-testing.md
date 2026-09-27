# Workday testing: real data, not guesses

`hub/workday.py` and `web/lib/workday.js` are tested against a **real** Workday
"View My Courses" export (`fixtures/workday_view_my_courses.xlsx`), not a
hand-made guess at the format. This matters: an earlier hand-made fixture
(built from third-party reference code, before we had a real export to check
against) turned out to assume a format real Workday never actually produces —
it silently hid two real bugs that only showed up once we tested against an
actual export:

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
`web/lib/workday_truncated.test.mjs` isolate the dimension bug specifically,
using a synthetic fixture; `tests/test_workday.py` / `web/lib/workday.test.mjs`
cover the rest against the real export).

## About the fixture

`fixtures/workday_view_my_courses.xlsx` is a **real** export (Sam's own,
2026W1, Biomedical Engineering), with only column A's "Name (student#) - ..."
prefix replaced by a placeholder (`"Student (00000000)"`) — every other
column, every real course code and title, is unmodified. That's a deliberate
exception to the repo's usual "fixtures must be fake or anonymised" rule,
made with the data owner's explicit, informed consent (they were told the
tradeoff and chose to keep the real course data rather than anonymise it
further).

## If you want to test with your own export

1. Download yours: Workday → Academics → Registration & Courses → **View My
   Courses** → Excel export.
2. Anonymise column A the same way (a one-off script, not something to
   automate into the parser — see git history around this file for the
   approach), or just don't commit it if you'd rather keep it local.
3. Run `uv run pytest tests/test_workday.py` / `cd web && npm test` against
   it and compare — if your export's structure differs from what's described
   above, that's a real finding worth posting to the Agent board (#15) per
   rule 6, since both parsers would need updating together.
