# SQL as the interface: raw layer, fusion views, `lauds sql`

> **ponytail:** stub. The database design is on hold for the overnight swarm
> (BRIEF.md), so tonight's `lauds/store.py` mirrors `main`'s `hub/db.py` schema
> and `lauds sql` is a plain read-only query. **Limit:** fusion lives in Python,
> sources are merged when they're written, and there's no raw layer to inspect.
> **Upgrade path:** everything below, as the first follow-up after the swarm.

## The pipeline

```
Collections  →  Naive concat  →  SQL (one SQLite file)  →  Fusion heuristics  →  UX
 (adapters)     (raw_<source>)                              (SQL views)         (lauds today, …)
```

1. **Collections:** each adapter fetches and parses into the shared model.
2. **Naive concat:** each source's rows are stored exactly as that source
   stated them, in `raw_<source>` tables (`raw_canvas`, `raw_prairielearn`,
   `raw_webwork`, …), all with the same columns. There's no merging and no
   dedupe here, so you can always recover what each platform actually said.
3. **SQL:** one SQLite file (`~/.local/share/lauds/lauds.db`). "Server" can
   simply mean `ssh <host> lauds sql "…"` wherever the file lives.
4. **Fusion heuristics as views:**
   - `items`: the fused list. The same quiz on two platforms counts once, and
     course codes are matched across systems.
   - `conflicts`: sources that disagree about the same item (for example due-date
     drift, `main` #23).
   - `clashes`: timetable overlaps, back-to-back rooms, deadline bunching.
   - Each view states the heuristic it applies in a comment, so a wrong row can
     be traced by comparing `raw_*` with the view.
5. **UX:** `lauds today`, `due`, `course`, `show` and `schedule` become canned
   queries over the views, and nothing else.

## The flag

| Command | Does |
|---|---|
| `lauds sql "SELECT …"` | one query (**tonight**: read-only URI `mode=ro`, SELECT/WITH only, `--json`) |
| `lauds sql` (no argument) | reads queries from stdin, `;`-separated, so you can pipe into it |
| `--format table\|json\|csv` | table for humans; json and csv for scripts and agents |
| `lauds sql --schema` | every table and view, with a one-line description of each column, so an agent can write correct queries without reading the code |
| `lauds db path` | prints the file's path, for `sqlite3`, Datasette or DuckDB (open with `?mode=ro`) |

## Open questions

- Should views be plain `VIEW`s, or rebuilt tables after each `sync`? Plain
  views are simplest; tables only make sense if fusion gets expensive.
- Should fuzzy matching (titles, course codes) be SQL or a Python step that
  writes a `matches` table? The second is probably clearer and testable, with
  the view joining on it.
- Parity: the fused `items` view must still satisfy the query goldens in
  `tests/oracle/queries/` (BRIEF's parity-to-superset rule).
