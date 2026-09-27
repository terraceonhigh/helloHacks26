# Live oracles (opt-in, networked)

Scripts here hit real servers, so they are not pytest tests (no `test_*.py`
names) and `uv run pytest` never collects them.

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
