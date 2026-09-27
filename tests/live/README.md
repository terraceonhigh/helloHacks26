# Live oracles (opt-in, networked)

Scripts here hit real servers, so they are not pytest tests (no `test_*.py`
names) and `uv run pytest` never collects them.

## `adapter_conformance.py`

Shared rules every adapter's real output must follow (tz-aware dues, absolute
non-doubled urls, unique `(source, url)`, `category == category_for(kind)`,
real Vancouver offsets, undated items kept, items join a course in `hub.db`).
Any oracle calls `adapter_conformance.check(courses, items, base=..., source=...)`
and `adapter_conformance.report(findings)`. Both oracles below run it when
passed `--conformance` (its FAILs count toward the oracle's exit status).
`tests/test_adapter_conformance.py` proves each rule against known-bad inputs.

## `canvas_selfhost_oracle.py`

Runs the real `hub.canvas._run` against the team's self-hosted Canvas
(see the canvas-selfhost README), seeds `[oracle]`-tagged edge-case data with
the admin token (idempotent: re-running reuses what's there), checks the
adapter's output against the raw Canvas payloads, then compares how `main`'s
`hub/db.py` and PR #41's (`origin/swarm/fix-pr33`) store the course rows.

```bash
git fetch                          # so origin/swarm/fix-pr33 is available for the db comparison
set -a; source .env; set +a        # CANVAS_BASE, CANVAS_TOKEN (student), CANVAS_ADMIN_TOKEN
uv run python tests/live/canvas_selfhost_oracle.py
```

Prints PASS/FAIL/INFO lines and exits 1 on any FAIL. Tokens come only from the
environment and are never printed; keep them in the gitignored `.env`.

Add `--conformance` to also apply `adapter_conformance.py`.

## `prairielearn_selfhost_oracle.py`

Runs the real `hub.prairielearn._run()` against a self-hosted PrairieLearn
loaded with the fake course in `prairielearn_testcourse/`, and prints
PASS/FAIL per check (non-zero exit on any FAIL). INFO lines record how real
PrairieLearn behaves where that differs from what the adapter assumes.

```bash
uv run python tests/live/prairielearn_selfhost_oracle.py            # default http://100.124.35.27:3002
uv run python tests/live/prairielearn_selfhost_oracle.py http://localhost:3002
```

The server is PrairieLearn's official image in local dev mode
([docs](https://docs.prairielearn.com/installing/)). There's no real auth: the
oracle picks the built-in test student with the dev-mode cookie
`pl_test_user=test_student`. No accounts or secrets are involved. On each run
it also clicks "Load from disk" (`/pl/loadFromDisk`) and self-enrolls the test
student.

Note: opening a Homework-type deep link as the student creates an assessment
instance for that student. That's harmless on this fake course.

### Start / stop (humboldt, rootless podman)

The fake course lives at `~/prairielearn/testCourse` on the host (a copy of
`prairielearn_testcourse/`), and the container is bound to the tailnet IP only.

```bash
# first time
podman pull docker.io/prairielearn/prairielearn:us-prod-live
podman run -d --name prairielearn-oracle \
  -p 100.124.35.27:3002:3000 \
  -v $HOME/prairielearn/testCourse:/course:Z \
  prairielearn/prairielearn:us-prod-live
# wait for "PrairieLearn server ready" in: podman logs -f prairielearn-oracle

podman stop prairielearn-oracle     # stop
podman start prairielearn-oracle    # start again (DB state is kept in the container)
podman rm -f prairielearn-oracle    # remove entirely (then re-run the command above)
```

To change the course, edit `prairielearn_testcourse/`, copy it to
`~/prairielearn/testCourse`, and re-run the oracle (it re-syncs). Keep
everything in it fake.

Elsewhere: the Docker equivalent is `docker run -it --rm -p 3002:3000 -v "$PWD/tests/live/prairielearn_testcourse:/course" prairielearn/prairielearn:us-prod-live`,
then pass `http://localhost:3002`.

Add `--conformance` to also apply `adapter_conformance.py`.
