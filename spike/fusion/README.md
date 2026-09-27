> **Not part of UBC Hub.** Agents working on `hub/`, `app.py`, `web/` or GitHub issues: ignore this directory (see `../README.md`).

# fusion-spike

A headless sensor-fusion spike for edtech providers. It has no GUI.

Every provider (WeBWorK, PrairieLearn, Moodle, Canvas, and so on) is a **sensor**.
An adapter reads what one student can see on that provider, as that student,
and turns it into **observations** (`fusion/model.py`). The fusion core
(`fusion/fuse.py`) works out which observations from different sources describe
the same course and the same piece of work. It fuses each group into one
**track**, and every fused field records its provenance. Disagreements between
sources are kept as conflicts; nothing is picked silently. `fusion/serve.py`
serves the result as JSON on 127.0.0.1.

The contract is in [SPEC.md](SPEC.md) (adapter contract, fusion rules, HTTP) and
[SCENARIO.md](SCENARIO.md) (the fake student, what gets seeded into each server,
and the exact fused table expected back). All data and credentials are fake.

```
fusion/model.py            observation / track model
fusion/adapters/<p>.py     one file per provider: NAME, fetch(session, base) -> Snapshot
fusion/fuse.py             entity resolution + fusion (pure)
fusion/run.py              collect snapshots (live, saved, or a mix), per-source error isolation
fusion/serve.py            stdlib JSON server
oracles/<p>/               stand up a real self-hosted server, seed SCENARIO, log in as fstudent
oracles/<p>_oracle.py      adapter output vs the server's own DB ground truth (--save-fixtures)
oracles/e2e_live.py        fetch every live server, fuse, compare with SCENARIO's table
oracles/sources.toml       live sources + replayed snapshots for --live
fixtures/<p>/              raw responses captured from the real servers
fixtures/snapshots/*.json  each adapter's Snapshot (real captures, plus the synthetic Canvas one)
tests/                     network-free pytest; test_e2e.py asserts SCENARIO's table exactly
```

## Provider status

| provider | server | adapter reads | status |
|---|---|---|---|
| WeBWorK 2.21 | real, local build of upstream's Dockerfile (`fx-webwork-*`, :8081) | student HTML (course page, set pages) | **live-verified**: oracle 45 PASS / 0 FAIL against MariaDB ground truth. Fixtures are real captures. |
| PrairieLearn | real, `prairielearn/prairielearn` in dev mode (`fx-prairielearn`, :3100) | JSON embedded in the home page, plus the assessments page HTML | **live-verified**: oracle 75 PASS / 0 FAIL against Postgres ground truth. Fixtures are real captures. Login uses dev mode's `dev_login` in place of SSO. |
| Moodle 4.5 LTS | real, `moodlehq/moodle-php-apache` + Postgres (`fx-moodle-*`, :8082) | AJAX web services the student session can call, plus assignment view pages | **live-verified**: oracle 125 PASS / 0 FAIL against Postgres ground truth. Fixtures are real captures. |
| Canvas | **none** (no published image, and a source build doesn't fit the machine) | REST API (planner items, courses, assignments) | **SYNTHETIC. Never run against a real Canvas.** Adapter and fixtures were written from the public API docs. `fixtures/snapshots/canvas.json` is regenerated from those fixtures and replayed next to the live sources. |

Fusion itself (`fuse.py`, `run.py`, `serve.py`) runs over the three live servers
plus the Canvas snapshot, and `oracles/e2e_live.py` confirms the result matches
SCENARIO exactly: 14 tracks from 19 observations, with the expected members, due
authorities, conflicts, evidence and statuses.

### Known deviations from SCENARIO (real limits, not bugs)

- **Lab 4's `action_url` is the course instance's assessments page, not a deep link.**
  Before an assessment opens, PrairieLearn lists it without a link and never shows
  the student its id; the real deep link returns 403 until 2026-10-20. The
  PrairieLearn snapshot says so in `notes`, and `/health` shows that note.
  The url carries the row label as a fragment (`.../assessments#L4`), so it stays
  that item's own: fusion never treats a generic link to the list page as link
  evidence (nor any url two items of one source share, nor a course page).
- **Problem Set 3's url changes over its life.** On a fresh seed it's
  `/assessment/2/`. Once the Homework is started (the PL oracle's click check
  starts it), PrairieLearn links the row to `/assessment_instance/1/`. The
  captured fixtures hold the started state, and `e2e_live.py` accepts either
  form. PS3 joins Moodle's M7 on title + due either way.
- The cross-links written into Moodle (`oracles/moodle/links.env`) and the Canvas
  fixture point at PrairieLearn's real quiz1 page
  `http://127.0.0.1:3100/pl/course_instance/1/assessment/3/` (assessment ids
  follow alphabetical sync order on a fresh seed).

## Setup

```bash
uv sync
```

Docker must be running. The three servers need about 11 GB of disk for images (PrairieLearn alone is 6.3 GB);
the WeBWorK image is built locally once, and its first build is slow.

## Bring up the oracles (real servers, seeded with SCENARIO)

Each script is idempotent: it brings the server up, seeds it from scratch or
tops it up, and generates random fake passwords into
`oracles/<p>/secrets.env` (gitignored, never printed).

```bash
bash oracles/webwork/up.sh        # http://localhost:8081/webwork2/math100_2026w1
bash oracles/prairielearn/up.sh   # http://127.0.0.1:3100/pl
bash oracles/moodle/up.sh         # http://localhost:8082  (must be "localhost": Moodle redirects other hosts)
bash oracles/canvas/up.sh         # no server; regenerates fixtures/snapshots/canvas.json
```

Each `oracles/<p>/README.md` covers teardown (`--down` / `--nuke` / `docker rm`)
and every real-server behaviour its adapter has to handle.

Check each adapter against its server's own database, and re-capture fixtures:

```bash
uv run python -m oracles.moodle_oracle --save-fixtures
uv run python oracles/webwork_oracle.py --save-fixtures
uv run python oracles/prairielearn_oracle.py --save-fixtures   # --no-click keeps PS3 unstarted
uv run python oracles/e2e_live.py                              # live fetch + fuse vs SCENARIO; exit 1 on mismatch
```

## Tests

```bash
uv run pytest
```

The tests are network-free. They replay the captured fixtures through each
adapter, unit-test the fusion rules, and in `tests/test_e2e.py` fuse
`fixtures/snapshots/*.json` and assert SCENARIO's expected table exactly. The
expected table is written out literally in `tests/e2e_expected.py`, which
`oracles/e2e_live.py` shares.

## Serve

```bash
uv run python -m fusion.serve --snapshots fixtures/snapshots          # replay saved snapshots
uv run python -m fusion.serve --live oracles/sources.toml --port 8765 # live servers + Canvas snapshot
```

In `oracles/sources.toml`, `[[source]]` entries are fetched live (adapter + login
+ secrets). `[[snapshot]]` entries replay a saved Snapshot file next to them.
Canvas uses a `[[snapshot]]` entry. A source that fails shows up as an error in
`/health` and doesn't stop the others.

```bash
curl -s localhost:8765/tracks | python3 -m json.tool       # fused list: overdue, then due ascending, undated last
curl -s 'localhost:8765/tracks?all=1&course=CPSC%20121'    # include done, one course
curl -s localhost:8765/tracks/4c09f2cd2cbe                 # one track: members, evidence, conflicts, provenance
curl -s localhost:8765/courses                             # resolved courses and each source's label
curl -s localhost:8765/observations                        # raw, unfused
curl -s localhost:8765/health                              # per source: ok/error, counts, fetched_at, notes
```

A trimmed `/tracks` row:

```json
{"id": "4c09f2cd2cbe", "course": "CPSC 121 / 2026W1", "title": "Quiz 1", "kind": "quiz",
 "status": "upcoming", "due": "2026-10-02T23:59:00-07:00",
 "action_url": "http://127.0.0.1:3100/pl/course_instance/1/assessment/3/",
 "sources": ["canvas", "moodle", "prairielearn"], "evidence_kinds": ["link", "title+undated"],
 "conflicts": 0}
```

Track ids are a stable hash of the sorted `(source, source_id)` members. Moodle
cmids are assigned at seed time, so an id containing a Moodle member can change
after a Moodle re-seed.
