# Brief: the overnight swarm on `lauds-cli` (2026-09-27/28)

Written by Terrace's concierge, the manager of the swarm. The contract is in
[BRIEF.md](../../BRIEF.md). The per-agent results are summarised here from the
workflow journal, and the headline numbers were re-run by the manager.

## Verdict

🟢 **The `lauds-cli` branch is in good shape.** 13 agents finished with no
errors in about 2 hours. **587 tests pass** (re-run by the manager with no
skips). Everything is pushed to `origin/lauds-cli`. The `main` checkout used as
the oracle is untouched.

## What exists now

- **`lauds`, a CLI-first Python package:** `login`, `sync`, `status`, `today`,
  `due`, `undated`, `course`, `show`, `schedule`, `textbooks`, `sql`
  (read-only), `export ics` and `config`, with `--json` on the query commands.
- **Adapters** under `lauds/adapters/`, one file each: canvas, canvas_ics,
  prairielearn, webwork, workday, bookstore, key_dates, brightspace, moodle,
  blackboard, piazza, plus `_captures` (the extension-capture dispatch).
- **Parity-to-superset** against `main` for every adapter's goldens, the 21
  query goldens and the `.ics` export goldens:
  - All 75 offline goldens reproduce byte-for-byte from `tools/harvest_oracle.py`
    (checked by the reviewer).
  - Live goldens come from `tools/harvest_live.py` (Canvas, PrairieLearn,
    WeBWorK) and `tools/harvest_live_moodle.py`.
  - `DIVERGENCES.md` is **empty**: no exceptions to parity were needed.

## Verification grades (after the fixer corrected overclaims)

| Grade | Adapters |
|---|---|
| live-verified: three-way check against humboldt, re-run and passing | Canvas, PrairieLearn, WeBWorK |
| docs-verified | Brightspace, key dates, queries, `export ics` |
| fixture-only | Moodle (live fixtures captured, but no `tests/live/moodle_live.py`), Workday, Bookstore, Blackboard, Piazza, canvas_ics, extension parsers |

## Review and fix round

The adversarial reviewer found 2 blockers, 9 majors and 13 minors. The fixer
checked each one independently and fixed both blockers, all 9 majors and 9 of
the minors (544 → 587 tests). The main ones:

- **Blocker:** `login`/`sync` couldn't drive 9 of the 11 adapters (their
  arguments were never passed through).
- **Blocker:** the extension-capture parsers weren't ported, and 4 of the 5
  extension goldens had no parity test.
- Expired sessions synced as "ok" with 0 items. They now report as stale.
- A re-login inside sync crashed (nested Playwright), and sync could open
  interactive logins for up to 300 s.
- A `canvas_ics` sync overwrote the Canvas API's richer rows (done, description,
  points).
- Undated items couldn't be seen from the CLI. There's now `lauds undated`.
- Moodle's calendar was silently cut off at 50 events, and the Bookstore cached a
  failed scrape as a 6-hour success.

## Still open

1. **Scrub the committed tokens:** a Moodle `sesskey`/`logintoken` (from the
   throwaway test server) and a public TikTok pixel token in a Bookstore page.
   This needs a scrubber fix and a re-harvest.
2. **Canvas undated `done`** comes from `has_submitted_submissions`, which is
   true if any student submitted. It needs `include[]=submission` and a live payload.
3. **Leftover "UBC Hub" names** in the `.ics` PRODID and UIDs. **Principal's
   call:** keep them (event IDs stay stable) or rename them (a DIVERGENCES entry,
   and duplicate events in calendars that already imported the export).
4. The Bookstore live golden was added by hand. It needs a `harvest_live_bookstore.py`.
5. WeBWorK's parity test undoes the redaction of `effectiveUser` with a shim
   instead of a consistent re-harvest.
6. Moodle's `to_course` has no stock-Moodle live path, and assignment/grade
   endpoints aren't wired in.

## Infrastructure left running

- humboldt (rootless podman as `terrace`): Canvas :3001, PrairieLearn :3002,
  WeBWorK :3003, and **Moodle :3004** (`moodle-oracle-web`, `moodle-oracle-db`,
  new tonight, disposable). **Principal's call:** keep them or remove them.
  humboldt's load was about 8.

## Proposed next steps

1. The first real sync: `lauds login canvas` on gala (it needs a visible
   browser), then `lauds today`.
2. `docs/sql-layers.md`: raw tables, fusion views, `lauds sql --schema`/stdin,
   `lauds db path`.
3. The materials fetcher (fill `Item.files`, following the heuristic-first rule
   in whiteboard #3), then the concierge's school-prep skill.
