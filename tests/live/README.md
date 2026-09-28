# tests/live: the live oracle harvest

`tools/harvest_live.py` runs MAIN's real adapters (`hub.canvas`, `hub.prairielearn`,
`hub.webwork`, all imported read-only from the oracle checkout,
`/sdcard/Projects/helloHacks26`) against last night's self-hosted Canvas,
PrairieLearn and WeBWorK on humboldt (`100.124.35.27`, tailnet-only — see
`BRIEF.md`'s "Live servers" section). It's the harvester the parity-to-superset
rule (`BRIEF.md`) means by "a raw fixture or live payload": it records every
raw HTTP response each adapter actually consumed, and turns the adapter's
output into a replayable golden. Not a pytest test (networked, and the
filename doesn't match `test_*.py`).

```bash
UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \
    ~/.local/bin/uv run --no-sync --project /sdcard/Projects/helloHacks26 \
    python /sdcard/Projects/lauds-cli/tools/harvest_live.py [adapter ...]
```

`adapter` is one or more of `canvas prairielearn webwork` (default: all
three, each isolated in its own try/except — one server being down never
stops the others). Prints a PASS-style summary line per adapter with its
verification grade (`live-verified` or `n/a` + why) at the end.

## What it produces

- **Raw fixtures**, copied verbatim from what the adapter received:
  `tests/fixtures/{canvas,prairielearn,webwork}/live_NN_<url-slug>.{json,html}`.
- **Goldens**, one per adapter for now (`case` = `"selfhost"`):
  `tests/oracle/{canvas,prairielearn,webwork}/live_selfhost.json`, in the
  shared golden format (see `BRIEF.md` / the swarm brief that commissioned
  this harvest): `adapter`, `case`, `inputs` (fixture paths, relative to
  `tests/fixtures/`), `oracle_call` (the exact main function(s) invoked),
  `now` (harvest time, ISO 8601 with offset), `extra` (call parameters:
  base URL, campus key, course code, the `start`/`end` window Canvas's
  planner needs), and `output` (`dataclasses.asdict()` of every
  `hub.models` record the adapter returned; a list key is present only if
  that adapter can produce that record type — WeBWorK's has no `courses`,
  since `hub/webwork.py` never builds one).
- Only this script writes `tests/oracle/`; regenerating a golden means
  re-running it, never hand-editing the JSON (`BRIEF.md` rule 6).

## Per adapter

- **Canvas** (`:3001`): needs `CANVAS_TOKEN` (a pre-provisioned student API
  token), read from `~/canvas-lms/secrets.env` over ssh straight into an
  env var — never printed, logged, or written anywhere. Runs
  `hub.canvas._run(req, start, end)` with `hub.canvas.BASE` monkeypatched
  to the self-hosted instance (no product-code change, same pattern the
  `origin/oracle/selfhost-canvas` branch script uses). The `[oracle]`-tagged
  edge-case data that script seeds was already present on humboldt when
  this ran (course id 2, `[oracle] CPSC 121 L1A 2026W1 Lab`, its 5
  assignments/1 quiz/1 event/1 graded submission) — re-seeding is
  idempotent (`seed()` in that branch's script) but wasn't needed here, so
  it wasn't re-run, to keep load on humboldt down.
- **PrairieLearn** (`:3002`): **needs no credentials at all.** In dev mode
  PrairieLearn logs every request in automatically; the only thing this
  script sends is the `pl_test_user=test_student` cookie, which selects the
  built-in test student. Runs `hub.prairielearn._run(req, campus_key, base)`
  directly (bypassing `resolve_campus()`, which would reject a bare IP/http
  URL — fine, since this is a fixed self-hosted test instance, not a
  student-pasted campus). `campus_key` is the synthetic
  `"prairielearn-selfhost"`, kept distinct from the real `"prairielearn"` /
  `"prairielearn_ok"` keys so a saved session or `source` value never
  collides with one.
- **WeBWorK** (`:3003/webwork2/fake101`): needs `WW_STUDENT_USER`,
  `WW_STUDENT_PASSWORD`, `WW_STUDENT_OTP_SECRET` from `~/webwork/secrets.env`
  over ssh, same as above. Logs in through the normal username/password form
  and the default TOTP step (RFC 6238, SHA1, 6 digits, 30 s — the login POST
  and its response, the only place a password/OTP code appears at all, are
  never recorded or written to disk). `hub/webwork.py` has no `_run()`; its
  real entry point for a known `base`+`course_code` is
  `_problem_sets(req, base, course_code)`, which calls `to_item()` over each
  `<li data-set-status>` on the one page it fetches. It never visits an
  individual set's own page, so `due=None` for a not-yet-open or past-due
  set is the documented, correct adapter behaviour (see the module
  docstring), not a gap in this harvest.

## Secrets handling

Every secret this script touches (Canvas student token; WeBWorK student
username/password/OTP secret, and the OTP code computed from it) is loaded
straight from an ssh command's stdout into a Python variable and registered
with a scrubber before anything is written to disk. Every fixture body is
passed through that scrubber (exact-value redaction of every secret it was
told about, plus generic patterns for CSRF/session tokens such as
PrairieLearn's `csrfToken` and WeBWorK's hidden `key` field) before being
saved — verified by grepping the written fixtures for each secret's literal
value after every harvest run in this session; none were found. The login
request/response themselves are simply never captured for WeBWorK (see
above), so a password or TOTP code never reaches a file at all.

## Re-running

Idempotent to re-run: it only reads from the three servers (Canvas and
WeBWorK) or reads a fixed dev-mode course (PrairieLearn's `pl_test_user`
cookie is read-only from this script's point of view, though opening a
Homework-type deep link does create an assessment instance for that
student server-side — harmless on the fake course, and this script never
follows a deep link, only the set-list/assessments pages). Overwrites the
same `live_selfhost.json` / `live_NN_*` fixture files each time, so a stale
golden is never left behind after a re-run.
