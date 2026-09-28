# tests/live/moodle_selfhost: the Moodle live oracle

`tools/harvest_live_moodle.py` runs MAIN's real `hub.moodle` (imported
read-only from the oracle checkout, `/sdcard/Projects/helloHacks26`)
against a disposable, self-hosted Moodle on humboldt
(`http://100.124.35.27:3004`, tailnet-only - see `BRIEF.md`'s "Live
servers" section), records every raw HTTP response the adapter's own code
actually consumed, and writes replayable goldens. Sibling of
`tools/harvest_live.py` (canvas/prairielearn/webwork); written as its own
script per this task's instructions rather than added to that file, which
belongs to the agent who wrote it.

```bash
UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \
    ~/.local/bin/uv run --no-sync --project /sdcard/Projects/helloHacks26 \
    python /sdcard/Projects/lauds-cli/tools/harvest_live_moodle.py
```

## What it produces

- **Raw fixtures** (`tests/fixtures/moodle/live_NN_<method>_<url-slug>.{html,json}`):
  the `/my/` dashboard page (read once for its `M.cfg.sesskey`) and the raw
  `/lib/ajax/service.php` batch responses, copied verbatim.
- **Two goldens**, since main's shipped code and a corrected call differ
  (see "Oracle bugs found" below) - both real, both `hub.moodle` functions
  applied to real captured data, neither hand-edited:
  - `tests/oracle/moodle/live_fake101.json` - `hub.moodle.fetch(base)` as
    main actually ships it. **Always empty** (`courses: [], items: []`)
    against a real Moodle site - see bug #1. This is main's genuine,
    reproducible ground truth, not a harvest failure, and is recorded as
    such rather than skipped.
  - `tests/oracle/moodle/live_fake101_calendar_only.json` -
    `hub.moodle.to_item` over a single, unbatched
    `core_calendar_get_action_events_by_timesort` call with `limitnum=50`
    (not main's hardcoded 100 - bug #2). Real field-mapping ground truth for
    a future adapter to match, even though no path in `hub/moodle.py` reaches
    it this way today.
- Only this script writes these two `tests/oracle/moodle/live_*.json` files.

## The fake course (`FAKE101`, all dates America/Vancouver)

Seeded by `setup_course.php` (idempotent; see "Start / stop" below), one
assignment per edge case from last night's other oracles' README tables,
plus a quiz and a submitted+graded assignment:

| activity | open | due | case |
|---|---|---|---|
| FAKE_A1_Past_Due | 2026-09-01 | 2026-09-20 23:59 | past due |
| FAKE_A2_Due_Soon | 2026-09-15 | now + 36 h | due within 48 h of capture |
| FAKE_A3_January_2027 | 2026-09-15 | 2027-01-15 23:59 | due after 2027-01-06 |
| FAKE_A4_Not_Yet_Open | 2026-10-15 | 2026-10-22 23:59 | not open yet |
| FAKE_A5_No_Due_Date | 2026-09-01 | (none, `duedate=0`) | no due date |
| FAKE_A6_Vancouver_Midnight | 2026-09-01 | 2026-09-30 00:00 | due at local midnight |
| FAKE_A7_Submitted_Graded | 2026-09-01 | 2026-09-10 23:59 | submitted by `fakestudent`, graded 95/100 by `fakeprof` |
| FAKE_Q1_Quiz | 2026-09-15 | closes 2026-10-05 23:59 | a quiz (`modulename=quiz`, not `assign`) |

Two students of note: `fakestudent` (used for the capture) and `fakeprof`
(editing teacher, used only server-side to grade FAKE_A7). Credentials live
only in `~/moodle/secrets.env` on humboldt (chmod 600) - never printed here.

Container names: `moodle-oracle-db` (postgres:16), `moodle-oracle-web`
(`moodlehq/moodle-php-apache:8.2-bookworm` + a plain `MOODLE_405_STABLE`
git checkout mounted as the docroot - the official, non-deprecated way to
run Moodle in a container without Bitnami's image). Published **only** on
`100.124.35.27:3004`, on their own `moodle-oracle-net` bridge network -
nothing else on humboldt was touched.

### Start / stop (humboldt, rootless podman)

```bash
# on humboldt, or piped over ssh (see harvest script's own ssh usage for the pattern)
tests/live/moodle_selfhost/run.sh up      # first time: network, secrets, git checkout,
                                           # image pulls, DB+web containers, CLI install
tests/live/moodle_selfhost/run.sh seed    # copies setup_course.php in, runs it, removes it
tests/live/moodle_selfhost/run.sh status  # podman ps + a login-page curl

tests/live/moodle_selfhost/run.sh stop    # stop (containers + data survive)
tests/live/moodle_selfhost/run.sh start   # start again
tests/live/moodle_selfhost/run.sh rm      # remove containers (volumes survive)
tests/live/moodle_selfhost/run.sh wipe    # remove containers + DB volume + network
```

`setup_course.php` is never left in the container's docroot (copied in,
run, `rm -f`'d again in the same step) - it uses Moodle's own documented
pattern for getting a data generator outside PHPUnit
(`phpunit_util::get_data_generator()`, exactly what
`admin/tool/generator/classes/course_backend.php` in Moodle core itself
does), not a public/writable endpoint, but there's no reason to leave an
admin-bypassing script reachable even briefly longer than it has to be.

## Oracle bugs found (live-verified, evidence below)

Both are properties of Moodle 4.5's own core code (`lib/db/services.php`,
`lib/ajax/service.php`), not this container's configuration - they
reproduce on any stock Moodle 4.5 install, not just this one.

1. **`hub.moodle._run()`'s batched AJAX call can never succeed.** It POSTs
   `core_enrol_get_users_courses` and
   `core_calendar_get_action_events_by_timesort` together in one call to
   `/lib/ajax/service.php`. But `core_enrol_get_users_courses`'s own
   registration in `lib/db/services.php` has no `'ajax' => true` (only
   `core_calendar_get_action_events_by_timesort` does), so
   `external_api::call_external_function(..., $ajaxonly=true)` rejects it
   with `servicenotavailable`. `lib/ajax/service.php` then `break`s out of
   its request loop on that first error and **never even attempts** the
   second (calendar) call - see its own comment: "an earlier step may be
   performing a dependant action ... you do not want steps 2 and 3 to
   happen if step 1 fails." The response is a one-element JSON array
   (just the courses call's error), not one entry per call. `hub.moodle._run`
   then does `course_result, events_result = results` on that one-element
   list and raises `ValueError: not enough values to unpack`, which
   `fetch()` swallows into `([], [])`.
   Evidence: `tests/fixtures/moodle/live_01_post_lib_ajax_service_php.json`
   (the raw one-element error response), plus
   `/home/terrace/moodle/moodle/lib/db/services.php:859-867` (the
   `core_enrol_get_users_courses` entry, no `ajax` key) vs. `:270-280` (the
   calendar entry, `'ajax' => true`) and `lib/ajax/service.php`'s request
   loop, both on humboldt.
2. **`core_calendar_get_action_events_by_timesort`'s own `limitnum` is
   capped at 50** by that external function's parameter validation, but
   `hub.moodle._run()` hardcodes `limitnum: 100`. Even called alone
   (routing around bug #1), the request fails with `"Limit must be between
   1 and 50 (inclusive)"` until `limitnum` is dropped to 50.
   Evidence: `tests/fixtures/moodle/live_03_post_lib_ajax_service_php.json`
   was captured with `limitnum=50` (succeeds, 6 events); the
   `limitnum=100`/batched attempt's failure is bug #1's fixture above (which
   would have hit this second problem too, had it gotten that far).
3. **The calendar feed omits `FAKE_A5_No_Due_Date` and `FAKE_A7_Submitted_Graded`
   entirely** (`live_fake101_calendar_only.json` has 6 items, not 8): it's a
   due-date timeline, so an item with no due date never appears, and an
   item the student has already submitted/been graded on drops off once
   it's no longer actionable. Not a bug - just something a future adapter
   needs another source for (e.g. `mod_assign_get_assignments` +
   `gradereport_user_get_grade_items`, already flagged as unimplemented
   follow-ups in `hub/moodle.py`'s own module docstring) if it wants
   "no due date" or "already done" items to show up at all.

These aren't listed in `../../../DIVERGENCES.md`: that file is for a
*record* lauds emits that disagrees with a value the oracle's golden
actually contains, and here the oracle's own golden output is genuinely
empty (bug #1/#2) or genuinely missing those two records (bug #3) - per
`BRIEF.md`'s parity rule, lauds emitting *more* than an empty/partial
oracle golden needs no divergence entry at all. A future `lauds/adapters/
moodle.py` should route around both bugs from the start (split the batch,
cap `limitnum` at 50) rather than reproduce them.

## Verification grade

**live-verified**: both the failure mode (bug #1/#2, on the batched/
over-limit call) and the corrected call's real field mapping (`to_item`
over 6 real events, all 7 due-date edge cases from the table above that the
calendar feed can represent) were confirmed against a real, self-hosted
Moodle 4.5 instance, not docs or a hand-written fixture. `to_course` has no
live-verified path at all yet: no call in `hub/moodle.py` that can reach a
real course list on a stock Moodle install was found (see bug #1) - it
remains fixture-only (`tests/fixtures/moodle/parse_capture.json`).

## Secrets handling

`MOODLE_STUDENT_USER`/`MOODLE_STUDENT_PASSWORD` are read from
`~/moodle/secrets.env` over ssh straight into Python variables and
registered with a scrubber before anything is written to disk (same
pattern as `tools/harvest_live.py`). The login POST itself is made on the
harvest script's own `requests.Session` and is never recorded; only the
adapter's own `GET /my/` and `POST /lib/ajax/service.php` calls (made
*after* login, on the now-authenticated session) go through the recording
wrapper. Every fixture body is scrubbed for the literal username/password
and for `sesskey`/`logintoken` patterns before being saved - verified by
grepping the written fixtures for the literal password value after the
harvest; not found.

## Why headless-`requests`, not Playwright, for login

`hub.moodle.login()`/`hub.site.login()` open a **visible** browser and wait
for a human to sign in - correct for a real student, unusable for an
unattended overnight capture. Moodle's login form here is a plain
username/password HTML form (not SSO-fronted - confirmed by reading
`login/index.php`'s rendered page before writing this script), the same
situation `tools/harvest_live.py`'s WeBWorK harvester already handles by
filling the form with plain `requests` instead of driving a browser: once
authenticated, `hub.moodle._sesskey`/`_ajax` only need an object with
`.get()`/`.post()` returning `.status`/`.ok`/`.text()`, which a
`requests.Session` satisfies identically to a Playwright
`APIRequestContext`. Playwright (`/home/.venvs/hub-oracle` and
`/home/.venvs/pw` both have it, 1.63.0) was confirmed available but wasn't
needed.

## Re-running

Idempotent: `setup_course.php` and `run.sh up`/`seed` check for existing
rows/containers before creating anything, and the harvest script overwrites
the same two `live_*.json` goldens and `live_NN_*` fixtures each run, so a
stale golden is never left behind.
