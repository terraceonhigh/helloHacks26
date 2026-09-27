# Parity oracle (#31)

`check_parity.py` checks that `web/` shows what the frozen `app.py` shows, on one
fixture `hub.db` it builds from fake rows (overdue, soon, done, no-due, every
category, graded and ungraded courses, a course with no items). It's opt-in:
plain `uv run pytest` doesn't collect it.

```bash
uv run playwright install chromium                            # once
uv run python tests/parity/check_parity.py                    # this checkout's web/
uv run python tests/parity/check_parity.py --web-ref origin/sam
uv run python tests/parity/check_parity.py --web-dir ../other/web --keep-logs
```

It renders `app.py` with Streamlit's `AppTest` (Sample data off), runs this
checkout's `hub.api` plus `next dev` (with `NEXT_PUBLIC_HUB_API`) on the same DB, and
reads the DOM with Playwright. It then prints a PASS/FAIL table per tab and exits 1
on any FAIL. `--web-ref` extracts that ref's `web/` into a temp dir and runs
`npm ci` there once. `app.py` and `hub/api.py` always come from the checkout you
run it in. It picks free ports, so it needs local port binding (not inside a
network sandbox).

Checked: row set, order, Urgency text (case-sensitive), Due (as an instant),
overdue set and rows with Hide overdue off and on, done/no-due never shown,
Show next 5 and 10, empty-state text, tab labels, Sample toggle presence and
default. For the Courses tab, `app.py` has none, so it's checked against
`hub.db` directly (courses, title/term/grade, per-course rows, Urgency).
`WARN` rows (Due display format, `Sat Sep 26, 4:28 pm` vs
`Sat, Sep 26, 4:28 PM`) are cosmetic and don't change the exit code.
