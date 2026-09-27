PL_QUIZ1_URL = http://127.0.0.1:3100/pl/course_instance/1/assessment/3/

# Canvas fixtures: SYNTHETIC

**Every file here is SYNTHETIC.** Authored on 2026-09-27 from Canvas's public
REST API docs (https://canvas.instructure.com/doc/api/: Planner, Courses,
Assignments, Pagination). **Never verified against a live Canvas.** There is no
Canvas oracle in this spike (no published image, and a source build doesn't fit
the machine). Each JSON object carries a `_SYNTHETIC` key that real Canvas does
not send. The adapter ignores unknown keys.

## The one constant

`PL_QUIZ1_URL` (line 1) is the PrairieLearn quiz1 deep link that C1's
description points at. It is set to PrairieLearn's real quiz1 page (integrator, 2026-09-27). If PL's ids change,
replace it everywhere (line 1 of this file and `assignment_51001.txt`):

    old='<current PL_QUIZ1_URL on line 1>'
    new='<PL quiz1 url from fixtures/snapshots/prairielearn.json>'
    sed -i "s#$old#$new#g" fixtures/canvas/README.md fixtures/canvas/assignment_51001.txt
    uv run python oracles/canvas_fixture_snapshot.py

`tests/test_canvas.py` reads the constant from line 1, so it stays green after
the swap.

## Files

| file | request | what |
|---|---|---|
| `index.json` | - | request -> body file + response headers (incl. `Link`) for the fake session |
| `courses.txt` | `GET /api/v1/courses?include[]=term&per_page=100` | CPSC_121_101_2026W1, term "2026 Winter Term 1" |
| `planner_items_p1.txt` | `GET /api/v1/planner/items?start_date=..&end_date=..&per_page=50` | page 1: C2 "Tutorial 2 worksheet", Link rel="next" (lower-case `link` header) |
| `planner_items_p2.txt` | the rel="next" URL (`page=bookmark:...`) | page 2: C1 "Quiz 1 (PrairieLearn)", no next |
| `assignment_51001.txt` | `GET /api/v1/courses/4201/assignments/51001` | C1: external_tool, description links PL_QUIZ1_URL |
| `assignment_51002.txt` | `GET /api/v1/courses/4201/assignments/51002` | C2: online_upload, description links a Canvas file (same host, not a link out) |

The body files are `.txt` because each one starts with `while(1);`, which is what
Canvas prepends to JSON served to a cookie session. That's the browser-captured SSO
path the adapter uses.

Times are UTC (`Z`), as Canvas's API returns them. C1 is due
`2026-10-03T06:59:59Z` (2026-10-02 23:59:59 PDT: Canvas's "11:59pm" is :59
seconds). C2 is due `2026-10-01T19:00:00Z` (12:00 PDT).

## What is from the docs and what is from memory

- From the docs (fetched 2026-09-27): planner item shape (`plannable_type`,
  `plannable_id`, `plannable`, `submissions` object or `false`,
  `planner_override.marked_complete`, `html_url`, `course_id`), course shape
  with `include[]=term`, the assignment object (`description`, `due_at`,
  `unlock_at`, `submission_types`, `external_tool_tag_attributes`, `html_url`),
  and Link-header pagination (opaque absolute URLs; header name case not
  guaranteed; `rel="last"` may be missing).
- **Not in the current docs text, from known Canvas behaviour:** the
  `plannable_date` field on planner items (the docs example omits it), the
  `submissions.submitted` key, the `while(1);` prefix on cookie-session JSON,
  planner `page=bookmark:` cursors, and the planner's assignment `plannable`
  having no `description` (so the adapter fetches the assignment for it).
- The docs site says it's moving to developerdocs.instructure.com (redirect
  after 2026-07-01, still served on 2026-09-27).
