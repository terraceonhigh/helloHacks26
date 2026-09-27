# HANDOFF: fusion spike → PM session

The long version, with the survey of `main`, the whiteboards and the open
questions, is `../HANDOVER.md`. This file is the pickup sheet.

## Corrections to the handoff request

- **Tests: 182, not 237.** `uv run pytest` in this directory passes 182, all
  network-free.
- **The "3 MCP servers" are Docker containers.** They're the self-hosted test
  servers (`fx-webwork`, `fx-prairielearn`, `fx-moodle`). There's no MCP server
  in this spike.

## What it is and how it relates to `main`

A standalone, headless project with its own `pyproject.toml`, built clean-room:
no code from `hub/` was read or copied. Nothing outside `spike/` imports it. The
repo-root `uv run pytest` skips it (via `../conftest.py`), and CI only runs `tests/`.

- **Its own model.** Observations (one source's claim) are fused into tracks,
  with provenance for each field and recorded conflicts (`fusion/model.py`). It
  doesn't use `hub/models.py`.
- **`fusion/fuse.py` is the cross-source join `main` lacks.** It resolves courses
  across label styles and merges items on link or title+due evidence. The due
  date comes from the site where the work is submitted; other sources' dates are
  kept as conflicts.
- **The adapters compared with `main`:**

| Adapter | On `main`? | Spike |
|---|---|---|
| `canvas` | yes (`hub/canvas.py`) | **duplicate**, rewritten clean-room against the spike's model |
| `prairielearn` | yes (`hub/prairielearn.py`) | **duplicate**, rewritten clean-room |
| `moodle` | no (`main` has only the generic `.ics` parser) | **new** |
| `webwork` | no (only a branch-side oracle exists) | **new** |

## How to run

```bash
cd spike/fusion
uv sync
uv run pytest                                            # 182 tests, network-free
uv run python -m fusion.serve --snapshots fixtures/snapshots   # replay captured data
curl -s localhost:8765/tracks | python -m json.tool      # also /tracks/<id> /courses /observations /health
```

## The 3 test servers (Docker)

Each lives in `oracles/<name>/`, with an idempotent `up.sh` that builds (if
needed), starts and seeds `SCENARIO.md`.

| Server | Containers | Port | Notes |
|---|---|---|---|
| WeBWorK 2.21 | `fx-webwork-app`, `fx-webwork-db` | 8081 | local slimmed image build: upstream publishes none |
| PrairieLearn | `fx-prairielearn` | 3100 | `prairielearn/prairielearn:latest`, fake course mounted |
| Moodle | `fx-moodle-app`, `fx-moodle-db` | 8082 | base URL must be exactly `http://localhost:8082` |

```bash
dockerd &                                   # if the daemon isn't running
oracles/webwork/up.sh && oracles/prairielearn/up.sh && oracles/moodle/up.sh
uv run python oracles/<name>_oracle.py      # per-adapter check against DB ground truth
uv run python oracles/e2e_live.py           # the whole fused table, live
uv run python -m fusion.serve --live oracles/sources.toml
```

Credentials are generated into `oracles/<name>/secrets.env`, which is gitignored,
so a new machine regenerates them via `up.sh`. Stop the servers with
`docker compose -p fx-webwork down`, `docker compose -p fx-moodle down` and
`docker rm -f fx-prairielearn`, or see each README.

## Verified against a real endpoint vs fixtures only

- **Real, self-hosted:**
  - Moodle, WeBWorK and PrairieLearn are each checked against independent
    database ground truth: 0 failures.
  - The full fused table checks out live: 19 observations become exactly the
    14 expected tracks.
- **Fixtures only:**
  - **Canvas** is written from the public REST docs and has never touched a live
    Canvas.
  - **Login flows:** the oracles use local passwords, and PrairieLearn uses its
    dev login. CWL/Duo is untested.
- **Nothing is verified against a real UBC account.** All data is fake.

## Left out of the commit

Nothing was withheld beyond what's already gitignored:
- `oracles/*/secrets.env` and `oracles/prairielearn/secrets.pl-config.json`,
  which hold the fake servers' passwords;
- `.venv/`.

The scan found no tokens, cookies, real calendar-feed URLs, saved browser
sessions, or real names or student numbers. The session keys in fixtures are
scrubbed to `FXSESSKEY`, the feed URL is on `example.invalid`, and every person
is the fake `fstudent`/`fprof`.

## Unfinished

- **A live Canvas oracle.** `humboldt`'s self-hosted Canvas is the natural one.
- **Real SSO session capture.** Adapters take an already-authenticated
  `requests.Session`.
- **`Observation.aliases`**, for URLs that change: PrairieLearn assessment →
  instance, and Moodle ids after a reseed.
- **Lab 4 has no deep link** until it opens. PrairieLearn hides the id.
- **`done` paths not exercised live:** Moodle `done=True`, WeBWorK gateway
  quizzes, and PrairieLearn, where `done` is always `None`.
- **No refresh endpoint:** `serve` fetches once at startup.
- **Unreviewed rule choices** the agents made where the spec was silent: see
  `../HANDOVER.md` §6.
- **Not integrated with `main` in any way.** That's a decision for the PM, not
  something this spike assumes.
