# `lauds` CLI

Entry point: `lauds.cli:main` (`pyproject.toml`'s `[project.scripts]`). Every
command reads/writes the store at `paths.db_path()` (default
`~/.local/share/lauds/lauds.db`, or everything under `$LAUDS_HOME` when set).

```
lauds login <source> [--opt KEY=VALUE ...]
lauds sync [source...] [--timeout SECONDS]
lauds status [--json]
lauds today [--json]
lauds due [--week | --days N] [--course CODE] [--json]
lauds undated [--course CODE] [--json]
lauds course <code> [--json]
lauds show <id> [--json]
lauds schedule [--date YYYY-MM-DD] [--json]
lauds textbooks [--course CODE] [--json]
lauds sql "<SELECT/WITH query>" [--json]
lauds export ics [--out FILE] [--kind KIND]
lauds config set <key> <value>
```

## Commands

- **`login <source> [--opt KEY=VALUE ...]`** — runs that adapter's
  interactive login (a real, visible browser; only the session is kept,
  never a password), or says "no login step needed" for a token/no-auth
  adapter that has none. Some adapters' `login()`/`fetch()` need more than
  a saved session — WeBWorK needs `base`; Bookstore needs `program`/`term`;
  Canvas's optional token path needs `access_token`; and so on. `--opt` (
  repeatable) supplies those by parameter name for this one call, and — if
  `login()` succeeds — saves them for later, same as `config set
  <source>.<key> <value>` (below): a later `sync` needs no `--opt` at all.
  A missing required value is reported by name (`needs --opt base=<value>`),
  never a bare `TypeError`.
- **`sync [source...]`** — fetches and saves sources (default: every
  adapter `lauds.adapters` discovers). Each source's saved config
  (`config set <source>.<key> <value>` / a prior `login --opt`) is matched
  against its `fetch()`'s own parameter names and passed through as kwargs
  — a required one with nothing configured fails clearly ("needs config:
  `<source>.<key>`"), never a bare `TypeError`. Each source gets its own
  try/except and a hard per-source `--timeout` (default 60s, via
  `lauds.sync`'s daemon-thread runner — a hung adapter is abandoned and
  reported as a timeout, never left to block the others). `NotLoggedIn` is
  recorded as **stale** (`status`'s `stale` column, error `"re-login
  needed"`), never silently partial — sources that *did* succeed are still
  saved, and a session-based adapter with no saved session at all is
  reported stale too, never opened as an interactive browser mid-`sync`
  (only `lauds login` does that). Exit code is non-zero iff any source
  failed. A lockfile (`$LAUDS_HOME_or_data_dir/sync.lock`) keeps two `sync`
  runs from overlapping; a second one exits immediately (code 3) instead of
  waiting. `--json` prints only the JSON array on stdout; the per-source
  human lines go to stderr instead so the two never mix on one stream.
- **`status`** — one row per known adapter (whether ever synced or not):
  last attempt/success, ok/never, stale, and the last error.
- **`today`** — items due today, America/Vancouver.
- **`due`** — items due within a window: `--week` (7 days), `--days N`, or
  14 days by default; includes anything already overdue. `--course` filters
  to one course (code is canonicalised, so `cpsc121` matches `CPSC 121`).
- **`undated`** — items with no due date at all (a WeBWorK not-open/past-due
  set, Canvas's own `to_undated_item`, ...), most recently saved first;
  never shown by `today`/`due` (both filter on a due date) - BRIEF finding:
  these used to be reachable only via `show <id>` or `sql`. `--course`
  filters to one course code.
- **`course <code>`** — that course's info, its due items *and* its undated
  ones (see `undated` above), its textbooks and its recurring meetings.
- **`show <id>`** — one item in full: description, points, files (name,
  kind, a direct download/deep link).
- **`schedule`** — every recurring class meeting; `--date` narrows to
  meetings that occur on that one calendar date (weekday + term range).
- **`textbooks`** — required first, then by title; `--course` filters.
- **`sql "<query>"`** — ad-hoc read access to the store. The connection is
  opened `mode=ro` (SQLite itself refuses a write) *and* the query text is
  checked to start with `SELECT`/`WITH` and be a single statement — two
  independent guards, either one alone would do, both are cheap.
- **`export ics`** — `lauds/export_ics.py` (a port of main's
  `hub/export_ics.py`) turns every dated upcoming item into one merged
  `.ics` feed; `--out FILE` writes it there (default: stdout), `--kind`
  keeps only that one kind (subscribing to several per-kind feeds side by
  side is how a calendar app gives each its own colour — see that module's
  docstring). Checked against `tests/oracle/export_ics/*.json` byte-for-byte
  by `tests/parity/test_export_ics.py`.
- **`config set <key> <value>`** — `<key>` is either `<source>.<key>` (an
  adapter's own config, e.g. `config set webwork.base https://...` or
  `config set bookstore.term 2026W1` — read by `sync`/`login` as described
  above) or a bare flat key (e.g. `config set canvas-feed-url <url>`, kept
  for anything that isn't tied to one adapter's `fetch()`/`login()`
  parameters). Stored at `$LAUDS_HOME_or_config_dir/config.json`, chmod
  0600, and never echoed back in full (only a short masked prefix/suffix).

## `--json` schema

Every query command accepts `--json` for a stable machine-readable form
instead of the human table (dates always America/Vancouver in the table;
ISO 8601 with original offset in JSON).

**Item rows** (`today`, `due`, `course`'s `"items"`) — `lauds.compat`'s main
Item projection *minus* `files` (a query row doesn't carry it), plus `id`
and `status` (`lauds.models.status_of`, recomputed fresh every call, never
stored):

```json
{
  "id": 1, "course": "CPSC 121", "category": "deadline", "kind": "quiz",
  "title": "Quiz 2", "due": "2026-09-28T08:29:24.783381+00:00",
  "url": "https://canvas.example/courses/7/quizzes/2", "source": "demo",
  "done": null, "status": "soon"
}
```

**`show <id>`** — the fuller shape above plus `description`, `points`,
`files` (list of `{name, url, kind}`) and `extra` (adapter-specific JSON).

**`textbooks`** — `{course, title, isbn, required, price, url}`.

**`schedule`** — `{course, kind, days, start_time, end_time, location,
term_start, term_end, source}` (`days` as a list, e.g. `["MO","WE","FR"]`).

**`course <code>`** — `{course: {code, term, title, grade} | null, items:
[...], textbooks: [...], schedule: [...]}`.

**`status`** — `{source, last_attempt, last_success, ok, counts, error,
stale}` per adapter (`ok`/`stale` are `null`/`false` before the first sync).

**`sync --json`** — a list of `{source, ok, counts, error, stale}`.

**`sql --json`** — a list of `{column: value}` rows (`cursor.description`'s
own column names).

## Demo transcript

Real entry point, real `uv run`, a fake in-process adapter (`NAME = "demo"`,
three items/one textbook/one meeting on `CPSC 121`) standing in for a real
one so the transcript below needs no network or credentials:

```
$ lauds sync demo
demo: ok (courses 1, items 3, meetings 1, textbooks 1)

$ lauds status
SOURCE       OK    LAST SUCCESS         STALE  ERROR
blackboard   never
bookstore    never
brightspace  never
canvas       never
canvas_ics   never
demo         yes   2026-09-27 19:29
moodle       never
piazza       never
prairielearn never
ubc_key_dat… never
webwork      never
workday      never

$ lauds today
(nothing)

$ lauds due --week
DUE              STATUS   COURSE     KIND       TITLE                        ID
2026-09-28 01:29 soon     CPSC 121   quiz       Quiz 2                       1
2026-10-01 19:29 upcoming CPSC 121   assignment Problem Set 3                2

$ lauds due --days 30 --course "CPSC 121"
DUE              STATUS   COURSE     KIND       TITLE                        ID
2026-09-28 01:29 soon     CPSC 121   quiz       Quiz 2                       1
2026-10-01 19:29 upcoming CPSC 121   assignment Problem Set 3                2
2026-10-22 19:29 upcoming CPSC 121   assignment Problem Set 4                3

$ lauds course "CPSC 121"
CPSC 121  Models of Computation  (2026W1, grade 88.5)
DUE              STATUS   COURSE     KIND       TITLE                        ID
2026-09-28 01:29 soon     CPSC 121   quiz       Quiz 2                       1
2026-10-01 19:29 upcoming CPSC 121   assignment Problem Set 3                2
2026-10-22 19:29 upcoming CPSC 121   assignment Problem Set 4                3

$ lauds show 1
[1] Quiz 2  (CPSC 121)
  deadline/quiz  due 2026-09-28 01:29  status=soon
  points: 10.0
  url: https://canvas.example/courses/7/quizzes/2

$ lauds schedule
COURSE     KIND      DAYS        START  END    LOCATION
CPSC 121   lecture   MO,WE,FR    10:00  11:00  ICCS 101

$ lauds textbooks
COURSE     TITLE                        REQ  PRICE    ISBN
CPSC 121   Discrete Mathematics and It… yes  $145.50  9780073383095

$ lauds sql "SELECT title, due FROM items WHERE due IS NOT NULL ORDER BY due"
title | due
Quiz 2 | 2026-09-28T08:29:24.783381+00:00
Problem Set 3 | 2026-10-02T02:29:24.783381+00:00
Problem Set 4 | 2026-10-23T02:29:24.783381+00:00

$ lauds sql "DELETE FROM items"
lauds sql: only SELECT/WITH queries are allowed

$ lauds export ics --out demo.ics
wrote demo.ics (1214 bytes, 2 kinds)

$ lauds config set canvas-feed-url "https://canvas.ubc.ca/feeds/calendars/user_abc123secrettoken.ics"
canvas-feed-url set (http…cs)
```

`demo.ics`'s first event, showing the "Title [COURSE]" convention a Canvas
`.ics` feed's own inbound parser round-trips through:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//UBC Hub//ubchub//EN
X-WR-CALNAME:Lauds
BEGIN:VEVENT
SUMMARY:Quiz 2 [CPSC 121]
DTSTART:20260928T082924Z
UID:demo-d97161094c28fcc1@ubchub
CATEGORIES:Quiz
URL:https://canvas.example/courses/7/quizzes/2
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Quiz 2 [CPSC 121]
TRIGGER:-P2D
END:VALARM
```

(`lauds sync` with no source runs every discovered adapter; against this
worktree's real adapters that need live credentials or a browser session
that isn't set up in this demo environment, each one fails independently
and is reported — `sync`'s own point: one broken/unconfigured source never
stops the others, and nothing is silently partial.)
