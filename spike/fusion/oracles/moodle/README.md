# Moodle oracle (Moodle 4.5 LTS, host port 8082)

A real self-hosted Moodle seeded with the Moodle rows of `SCENARIO.md`. Fake
data and random fake passwords only.

## Up / seed / down

```bash
oracles/moodle/up.sh          # idempotent: pull, clone code (first time), install (first time), seed
oracles/moodle/up.sh --down   # stop containers, keep data
oracles/moodle/up.sh --nuke   # remove containers and volumes (next up.sh starts from zero)
```

- Containers: `fx-moodle-app` (`moodlehq/moodle-php-apache:8.3`, Apache+PHP),
  `fx-moodle-db` (`mirror.gcr.io/library/postgres:16-alpine`). Network
  `fx-moodle-net`. Volumes `fx-moodle-src` (shallow `MOODLE_405_STABLE`
  checkout, no `.git`), `fx-moodle-data` (moodledata), `fx-moodle-pg`.
- Site: http://localhost:8082 (bound to 127.0.0.1). `wwwroot` is exactly
  `http://localhost:8082`. Moodle redirects any other host name (for example
  127.0.0.1) to it.
- Install: `up.sh` writes `config.php` itself, then runs
  `admin/cli/install_database.php`. The first install takes about 3 minutes.
- Timezone: site settings `timezone` and `forcetimezone` are
  `America/Vancouver`, set with `admin/cli/cfg.php` so they're real DB
  settings. Both users also have that timezone.
- Seed: `seed.php` runs inside the container as www-data, using Moodle's own
  APIs and the core data generator. It's idempotent. Every activity has a
  course-module idnumber `fx-M<n>` (the SCENARIO id). A re-run keeps rows that
  match and deletes and recreates rows that drifted.
- `secrets.env` (gitignored, mode 600) is generated on the first `up.sh`:
  `FSTUDENT_USERNAME/PASSWORD`, `FPROF_*`, `MOODLE_ADMIN_*`, `MOODLE_DB_PASSWORD`.
- `links.env` holds the cross-platform deep links written into the
  descriptions. **The integrator owns it**: `WW_BASE` (WeBWorK course root, set
  page = `<WW_BASE>/<SET>/`) and `PL_QUIZ1_URL`. It's
  `http://localhost:3100/pl/course_instance/1/assessment/3`, the id the PL
  oracle had seeded when this was written. If PL is reseeded with different
  ids, edit it and re-run `up.sh`. M5's description is recreated with the new
  link, and the oracle reads the expected links from the same file.

## What's seeded

| SCENARIO | Moodle object | ids (fresh install; a drifted activity gets a new id when re-seeded) |
|---|---|---|
| courses | `MATH100-2026W1`, `CPSC121-101-2026W1`, `ENGL110-001-2026W1` (start 2026-09-01, end 2026-12-31) | course 2, 3, 4 |
| users | `fstudent` Fake Student (student in all 3), `fprof` Fake Professor (editingteacher in all 3) | |
| M1, M2, M5 | assignments with **no submission plugin** (pointer), description links WeBWorK/PL | cm 1, 2, 4 |
| M4, M6, M8 | assignments with online-text submission | cm 3, 5, 6 |
| M3, M7 | course calendar events (Midterm 1 lasts 90 min) | event 6, 7 |
| M9 | page resource, no date | cm 7 |

## Login (`login.py`)

`login(base, secrets)` does Moodle's manual-auth form: GET
`/login/index.php` to get the `logintoken`, then POST username, password and
logintoken. It returns a `requests.Session` holding the `MoodleSession` cookie.
At a school, that cookie comes from the SSO browser session instead. The
adapter only needs the cookie.

## Oracle

```bash
uv run python -m oracles.moodle_oracle                  # PASS/FAIL/INFO, exit 1 on FAIL
uv run python -m oracles.moodle_oracle --save-fixtures  # also rewrites fixtures/moodle/ + fixtures/snapshots/moodle.json
```

Ground truth comes from SQL run directly in `fx-moodle-db` (enrolments,
`course_modules` + `assign`/`page`, `event`, `assign_submission`,
`assign_plugin_config`, `config`), never from the adapter's own code path.

## Real-server behaviours an adapter must handle

1. **Browser sessions only get AJAX-flagged functions.** `/lib/ajax/service.php?sesskey=…&info=<fn>`
   with a JSON body `[{"index":0,"methodname":…,"args":{…}}]`. The sesskey is
   in `M.cfg` on any logged-in page (`"sesskey":"…"`). The following functions
   are verified AJAX-enabled on 4.5 and used:
   `core_course_get_enrolled_courses_by_timeline_classification`,
   `core_courseformat_get_state` (it returns a **JSON string** inside `data`,
   so it's decoded twice), and `core_calendar_get_calendar_monthly_view`.
   The following functions are **not** AJAX-enabled and return
   `servicenotavailable`: `mod_assign_get_assignments`,
   `mod_assign_get_submission_status`, `core_course_get_contents`,
   `core_calendar_get_calendar_events`, `core_enrol_get_users_courses`,
   `mod_page_get_pages_by_courses`. That's why the description, submission
   state and submit button come from the item's HTML page.
2. **A failed call returns HTTP 200**: `[{"error":true,"exception":{"errorcode":…}}]`.
   That includes a logged-out session or a bad sesskey (`servicerequireslogin`).
   The adapter raises `MoodleError` on either.
3. **The timeline classification `all` hides courses the student hid from
   their dashboard.** Use `allincludinghidden`.
4. **Dates are Unix epochs.** The instant is exact. The monthly view's days
   carry `timestamp` = the user's local midnight, and the adapter takes the UTC
   offset from that (the server's own offset, -07:00 before 2026-11-01).
5. **Undated activities aren't in the calendar at all** (M5, M9). The module
   list must come from the course (`core_courseformat_get_state`), and the
   dates are joined onto it by course-module id, parsed from the calendar
   event's `url` (`mod/assign/view.php?id=<cmid>`).
6. **The calendar's "Add submission" action is misleading.** It's offered even
   on assignments with no submission plugin enabled (seen on M1, "WeBWorK
   HW1"). Trust the assignment page: an `action=editsubmission` form is present
   only when the student can submit.
7. **Viewing `mod/assign/view.php` writes.** It inserts an
   `assign_submission` row with status `new` for the student, just as their
   browser does. GETting `…&action=editsubmission` also creates or opens a draft.
   The oracle checks `submit_url` by shape only and never GETs it.
8. **Submission state has language-independent CSS classes**:
   `td.submissionstatus{new,draft,submitted,reopened}`. The "no attempt" state
   has no class. The adapter treats "has a submit button, not submitted" as
   `done=False`, and a pointer assignment (nothing to submit) as `done=None`.
9. **Descriptions are filtered on output.** Moodle's activity-names autolink
   filter inserts `<a class="autolink" href="…/mod/assign/view.php?id=…">`
   into calendar event descriptions (seen: "assignment 1" in M4's due event).
   Only links to *other* hosts go into `links_out`.
10. **A calendar event's `url` is the course home page.** The event's own deep
    link is `viewurl` (`calendar/view.php?view=day&course=…&time=…#event_<id>`).
    That page shows `data-event-id="<id>"`.
11. **Responses carry the sesskey** (`editurl` in calendar events, `M.cfg`).
    Fixtures are scrubbed to `FXSESSKEY`. The fixture keys ignore it.
12. **Forums and labels** (for example the auto-created Announcements forum)
    aren't work. The adapter skips them and counts them in `Snapshot.notes`.
    Site, user and category calendar events are skipped the same way.
