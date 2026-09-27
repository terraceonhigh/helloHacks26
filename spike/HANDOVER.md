# Handover: fusion spike (2026-09-27)

For Terrace. This is what was found, decided, built and verified in the session
that produced `spike/fusion/`, and what's still open. Agents working on `hub/`,
`app.py`, `web/` or GitHub issues: ignore this directory (see `README.md`).

## 1. Where the main project stood (read-only survey of `main`, 868645c)

**What it wants to be.** "Palantir Gotham for students": a read-only, local-first
fusion layer. Providers are plugins that turn their data into one shared model.
Fusion (matching, dedupe, ranking, risk) happens only on that model.

**What `main` had:**

| Layer | State |
|---|---|
| `hub/models.py` | `Course`, `Item`, `Textbook`, plus `status_of` and a keyword-based `classify_urgency` |
| `hub/site.py` | shared browser login, saved session, pagination, 429 backoff |
| `hub/canvas.py`, `hub/prairielearn.py` | working adapters |
| `hub/ics.py` | parser, not called from anywhere |
| `hub/workday.py` | parser, not connected to the db or API (the web app has a JavaScript copy) |
| Bookstore | nothing |
| `hub/db.py`, `hub/api.py` | SQLite plus a stdlib JSON API |
| UIs | two: `app.py` (Streamlit) and `web/` (Next.js on Vercel) |
| tests | 55 passing, all network-free |

**Gaps between the code and the mission:**
1. **No cross-source join.** `db.save` matches courses by exact code text, so Canvas's
   `CPSC_121_101_2026W1` and Workday's `CPSC 121` become two courses.
   `normalise_course_code` and `dedupe` exist but only tests call them.
2. Two urgency approaches: the keyword heuristic is live, and a trained
   classifier (`.joblib`, synthetic data) is unused.
3. Leftovers. `hub/api.py` still serves a `ui/index.html` that was removed in the
   revert of #35. The sample data and the kind→category table are duplicated
   across `app.py` and `web/`.
4. Two frontends, with Workday parsing in both Python and JavaScript.

About 40 remote branches exist. Several touch these gaps
(`jacky-canonicalize-course-codes`, `oracle/pr33-course-join`, `jacky-item-files`,
and others). They were not read.

## 2. The whiteboards

- **#1** (`docs/handoff/terrace-whiteboard-2026-09-26.md`, on `main`) is a list of
  wants: Canvas, Workday, iCal, recordings, readings, "Gotham for Students". It
  also records the founding pain point: a prof put no due date on Canvas, and
  the PrairieLearn deadlines were only in the syllabus.
- **#2** (`terrace-whiteboard-2026-09-26-b.md`) exists **only on `pm/merge-gate`**
  and isn't linked from `AGENTS.md`, so agents working from `main` never see it.
  - **Targets:** PrairieLearn, Achieve/Macmillan, Moodle, WeBWorK.
  - **Asks:** deep links to each item's submission page, and a folder of files
    under each row.
  - **BLUF:** "the human is the subagent; the pane is the prompt list; a row is a
    prompt."
  - **Loop:** wake → check the pane → click → everything's ready → work → submit →
    repeat or sleep.
- Whiteboard #2 moves the bar from "what's due?" to "can I act on this row with
  nothing else open?"

## 3. Viability assessment (before building)

The per-provider `oracle/*` pattern already existed on branches, so the swarm
scaled an existing template. How good an oracle each provider can have:

| Tier | Providers | Oracle |
|---|---|---|
| **Real server** | Canvas, Moodle, PrairieLearn, WeBWorK, Sakai, Open edX, ILIAS | open source and self-hostable: a strong check |
| **Vendor sandbox** | Google Classroom, Blackboard | weaker |
| **No oracle** | Brightspace, Achieve/Macmillan, Gradescope, Piazza, Top Hat, Crowdmark, Workday | own-account captures only. Adapters here can't be checked |

**Caveats raised at the time:**
- The oracles test data parsing, not CWL/Duo session capture.
- Self-hosted Canvas isn't identical to Instructure's hosted Canvas.
- More adapters widen the input but don't fuse anything. The join, and "a row is
  a prompt", were the real missing piece. That's why the spike is built around a
  fake student seeded across every server.
- A parallel rewrite can read as going around the backend owner. Your call was:
  new adapters only, fusion, no GUI, kept out of the other agents' way.

## 4. What was built (`spike/fusion/`)

Built clean-room: an orphan worktree with no shared history, and build agents
barred from reading `hub/`. It's a standalone project with its own
`pyproject.toml`.

- **The contract** is three files: `SPEC.md` (fusion rules, adapter contract,
  HTTP API), `SCENARIO.md` (one fake student, 19 observations that must fuse to
  exactly 14 tracks) and `fusion/model.py`.
  - The model: **observations** (one source's claim about one thing) fuse into
    **tracks**. Each field records which source it came from, and conflicts are
    recorded, never silently resolved.
- **Adapters:**
  - `moodle`, `webwork` and `prairielearn` are each verified against a real
    self-hosted server in Docker.
  - `canvas` is built from the public REST docs only.
- **Fusion (`fusion/fuse.py`):**
  - Course resolution to `(subject, number, term)`.
  - Items are only compared within the same course.
  - Evidence is a link (strong), or the title plus a due date within 24 h.
  - Numbers in titles must be equal.
  - Items linked together are merged transitively, and a track holding two items
    from the same source is split.
  - The due date comes from the site where the work is submitted, and other
    sources' dates go in `conflicts`.
  - Status is computed at read time, and track ids are deterministic.
- **HTTP (`fusion/serve.py`):** `/tracks`, `/tracks/<id>`, `/courses`,
  `/observations` and `/health`, bound to 127.0.0.1. `/health` reports each
  source separately, so one broken source doesn't take down the others.
- **Oracles:** each `oracles/<provider>/` has an idempotent `up.sh`, seed
  scripts, `login.py` and a README of real-server quirks. The
  `oracles/<p>_oracle.py` scripts check against independent ground truth (direct
  DB queries). `oracles/e2e_live.py` checks the whole fused table live.

**The fused result (live):**
- **HW2:** WeBWorK and Moodle merge. Moodle's due date, 59 minutes off, is shown
  as a conflict.
- **Quiz 1:** PrairieLearn, Moodle and Canvas merge into one track. The Moodle
  pointer that had no due date gets PrairieLearn's date.
- **Problem Set 3:** merged on title and due date alone.
- **Not merged, correctly:** Quiz 2 vs Quiz 3, and "Assignment 1" in two
  different courses.
- **HW9 (January 2027):** kept at the server's printed PST.

The workflow used 9 agents: 5 build, 1 integrate, 2 adversarial verify, 1 fix.
It took about 1.3M subagent tokens and 63 minutes. The verifiers found 11 real
issues. Ten were fixed with regression tests. One was declined on purpose:
fetching links from unstarted PrairieLearn quizzes could start the attempt.

**Verified independently after the run:**
- `pytest` passes 182, none touching the network.
- `e2e_live.py` passes.
- All three oracles have 0 failures.
- No `hub/` references in the spike.
- No secrets in tracked files. The only matches were the fake identifiers from
  `SCENARIO.md`.
- The repo-root `uv run pytest` still runs its 55 tests. `spike/conftest.py`
  keeps it from collecting the spike, and CI only runs `tests/`.

## 5. Not proven / known limits

- **Canvas is synthetic.** It has never touched a real Canvas. `humboldt`'s
  self-hosted Canvas is the natural oracle.
- **Login is untested.** Oracles log in with local passwords, and PrairieLearn
  uses its dev login. Adapters take an already-authenticated session, so CWL/Duo
  capture is still untested.
- **Lab 4 has no deep link.** PrairieLearn hides the id until the lab opens, so
  the row points at the assessments list.
- **Some URLs change over time.** PrairieLearn's URL for Problem Set 3 changes
  once started, and Moodle's item ids change on reseed. An optional
  `Observation.aliases` field would fix this.
- **WeBWorK is a slimmed local image build** (no hardcopy/TeX). Its due dates for
  past-due and not-yet-open sets depend on the default set header.
- **Some `done` paths are untested live.** Moodle's `done=True` and WeBWorK's
  gateway-quiz paths are in code but no seeded data exercises them.
  PrairieLearn's `done` is always `None`.
- **One-shot server.** `serve` fetches once at startup; there's no refresh endpoint.

## 6. Decisions the agents made where the spec was silent (review these)

- On an equal due date, a submittable item beats a calendar event as the
  authority, which is why P2 beats M7.
- On link chains the authority is the end of the chain: Canvas → Moodle →
  PrairieLearn means PrairieLearn wins.
- The split pass keeps the strongest evidence first and warns.
- Only UBC-style terms are parsed (`2026W1`, "2026 Winter Term 1"). A course
  with no parseable term is left unresolved, never guessed.
- `homework` and `lab` needed a place in the kind ranking. The spec only listed
  exam > quiz > assignment > event.
- Duplicate `(source, source_id)` observations with different content: all
  copies are kept, one is picked deterministically, and a warning is emitted.

## 7. Open questions for you

- Should whiteboard #2 land on `main` and be linked from `AGENTS.md` so it
  actually governs?
- "The human is the subagent": is ranking for *what to pull next* or for *what's
  most alarming*?
- Files under a row: is the deep link alone Phase 0, or the files too? Either
  way it needs a model change.
- Is it worth adding `Observation.aliases` now, given the URL churn above?

## 8. How to run it

```bash
cd spike/fusion
uv sync
uv run pytest                                   # 182 tests, network-free
uv run python -m fusion.serve --snapshots fixtures/snapshots   # replay the captured servers
curl -s localhost:8765/tracks | python -m json.tool             # default port 8765
# live (needs Docker):
oracles/webwork/up.sh; oracles/prairielearn/up.sh; oracles/moodle/up.sh
uv run python oracles/e2e_live.py
uv run python -m fusion.serve --live oracles/sources.toml
```

Oracle credentials are generated into `oracles/<p>/secrets.env`, which is
gitignored, so a fresh machine regenerates them via `up.sh`.

## 9. State at handover

- Commits on `claude/repo-exploration-rqom92`: `5f4ea60` (the spike) plus this
  handover. **Not pushed.** The session's permission check blocked `git push`.
  Push it yourself, or allow it and ask again.
- The container is temporary: the local `fusion-spike` worktree and the running
  `fx-*` Docker servers disappear when it's reclaimed.
- Nothing was posted to GitHub: no issues, board comments or PRs.
