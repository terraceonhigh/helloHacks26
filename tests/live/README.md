# Live oracles (opt-in, networked)

Scripts here hit real servers, so they are not pytest tests (no `test_*.py`
names) and `uv run pytest` never collects them.

## `adapter_conformance.py`

Vendored unchanged from `oracle/adapter-conformance`: shared rules every
adapter's real output must follow. `tests/test_adapter_conformance.py` proves
each rule against known-bad inputs.

## `canvas_feed_oracle.py` (issue #47)

Checks `hub.ics.parse` on a real Canvas calendar feed against the Canvas REST
API, on the team's self-hosted Canvas. It reads the student's feed URL from
`/users/self/profile`, fetches it with no auth header, and compares each item's
title, course, kind (from the VEVENT `UID`), due instant and deep-link url with
the API's assignments and calendar events, then runs `adapter_conformance`.

```bash
set -a; source .env; set +a        # CANVAS_BASE, CANVAS_TOKEN (student), CANVAS_ADMIN_TOKEN
uv run python tests/live/canvas_feed_oracle.py                     # this checkout's hub/ics.py
uv run python tests/live/canvas_feed_oracle.py --candidate origin/main   # another ref's hub/ics.py
uv run python tests/live/canvas_feed_oracle.py --seed              # first add a FAKE announcement
```

Exits 1 on any FAIL. API items the feed leaves out (undated assignments) are
INFO, not FAIL. The feed URL is a secret like a token and is never printed.
`tests/test_canvas_feed_oracle.py` checks the comparison logic network-free.
