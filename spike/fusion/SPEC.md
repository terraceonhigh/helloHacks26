# Fusion spike: spec

Headless. No GUI. Many edtech providers go in, one fused list comes out over HTTP.

## The idea in one paragraph

Each provider is a **sensor**. An adapter turns what one provider says into
**observations** (`fusion/model.py`). The **fusion core** (`fusion/fuse.py`)
does entity resolution over observations from every sensor. It decides which
observations describe the same real-world thing (the same course, the same
piece of work) and fuses them into one **track** per thing. Each fused field
records its **provenance** (which source said it) and any **conflicts** (sources
that disagree). Nothing is silently picked. `fusion/serve.py` serves the tracks
as JSON. The student's loop: check the list, click a row, land on the page where
they do and submit the work.

## Layout

```
fusion/model.py            THE model. Owned by the lead; build agents don't edit it (report needed changes instead)
fusion/adapters/<name>.py  one file per provider: NAME, fetch(session, base) -> Snapshot
fusion/fuse.py             entity resolution + fusion (pure functions over observations)
fusion/serve.py            stdlib http.server on 127.0.0.1, JSON only
fusion/run.py              collect snapshots (live from configured servers, or from saved JSON), fuse, hand to serve
oracles/<name>/            everything to stand up a real self-hosted server, seed SCENARIO.md into it, and log in
                           (docker compose file, seed script, README). Fake data and fake credentials only.
oracles/<name>_oracle.py   live check: adapter output vs the server's own independent ground truth
fixtures/<name>/           raw responses captured FROM THE REAL SERVER by the oracle (for network-free tests)
tests/test_<name>.py       network-free tests against fixtures
tests/test_fuse.py         fusion tests
tests/test_e2e.py          the fused output of SCENARIO.md is exactly the expected table
```

## Adapter contract

```python
NAME = "moodle"
def fetch(session: requests.Session, base: str) -> Snapshot: ...
```

- `session` is already authenticated. How it got that way is not the adapter's
  business. At a real school it's a browser-captured SSO session. Against our
  oracle it's a local password login done by `oracles/<name>/login.py`. Keep
  login out of the adapter, so the same adapter works behind any SSO.
- Read what a **student** can read, as that student. Prefer the provider's JSON
  or web-service endpoints that the student's own session can call. Parse HTML
  only when no student-reachable JSON exists.
- Return every item the student can see, including undated ones (`due=None`)
  and not-yet-open ones (with `opens`).
- `url` is the item's own page, a deep link, not a course home page.
  `submit_url` is the page where the student submits, when it's different and
  knowable. `links_out` holds every URL in the item's description or body that
  points at a different host or platform. This is key fusion evidence.
- Every datetime is tz-aware. Honour the offset or zone the server itself
  reports. Never re-derive it from a zone name if the server printed one.
  (Real case: WeBWorK's bundled tzdata disagrees with the OS about BC after
  2026-11-01. The server's instant is the one the student is held to.)
- A broken source must not break the others. `fetch` raises, and `run.py`
  catches it per source and reports it in `/health`.
- No new dependencies without telling the lead. Available: requests,
  beautifulsoup4, icalendar, pytest.

## Fusion rules (fusion/fuse.py)

1. **Courses.** Parse every `CourseObservation.label`/`title` into a canonical
   `CourseKey(subject, number, term)`. Examples: `CPSC121-101-2026W1`,
   `cpsc121_2026w1`, `CPSC 121: Models of Computation, 2026 Winter Term 1`,
   `CPSC_121_101_2026W1` all resolve to `CPSC 121 / 2026W1`. The section is
   kept as an attribute, never part of the key. A label that can't be parsed
   becomes its own course and gets a warning. It's never guessed into another.
2. **Blocking.** Only observations in the same resolved course are ever
   compared. Two observations from the **same source** are never merged,
   unless they have the same `source_id`.
3. **Evidence** between two observations A and B (different sources, same course):
   - `link`: A's `links_out` contains B's `url` or `submit_url`, or the other way
     round, after normalisation (scheme, host case, trailing slash, and query
     params that don't identify the item). **Strong: merge on this alone.**
   - `title`: the normalised titles match. Normalising lowercases, drops platform
     words ("webwork", "prairielearn", "moodle", "canvas"), drops filler
     ("due", "the", "(online)"...), and expands abbreviations (`hw`→homework,
     `ps`→problem set, `mp`→machine problem). **Every number must be equal**:
     "Quiz 2" never matches "Quiz 3".
   - `due`: both are set and within 24 h of each other.
   - Merge when `link`, or when `title` + (`due`, or one side undated).
     Record which evidence fired, and the due delta, on the track.
4. **Transitive merge** via union-find, then a sanity pass: a track may never
   hold two observations from the same source with different `source_id`. If
   one would, split it and emit a warning.
5. **Fused fields**, each with provenance:
   - `due`: from the **submit authority**. That's the observation whose `url`
     or `submit_url` is where the work is actually submitted: the one other
     observations link *to*, or failing that the only one with a
     `submit_url`. Failing that, the earliest due. Any other observation whose
     due differs by more than 5 minutes goes into `conflicts`.
   - `title`: the submit authority's title.
   - `kind`: the most specific kind (exam > quiz > assignment > event).
   - `action_url`: the submit authority's `submit_url` or `url`, the one link
     the row opens.
   - `links`: every source's url, labelled by source.
   - `opens`, `done` (`done` is true if the submit authority says so), `weight`.
6. **Status** is computed at read time, never stored: `done`, `overdue`,
   `due_soon` (within 48 h), `upcoming`, `not_open`, `undated`.
7. **Ordering** for `/tracks`: overdue, then by due ascending, with undated last.
   Done tracks are hidden unless `?all=1`.
8. Deterministic: the same observations always give the same track ids.
   A track id is a stable hash of its sorted `(source, source_id)` members.

## HTTP (fusion/serve.py)

Stdlib `http.server`, bound to 127.0.0.1, JSON only.

- `GET /tracks[?all=1&course=CPSC%20121]`: the fused list.
- `GET /tracks/<id>`: one track with its full observations, evidence and conflicts.
- `GET /courses`: resolved courses with their per-source labels.
- `GET /observations`: raw, unfused (for debugging fusion).
- `GET /health`: per source: ok/error, the error message, observation counts, fetched_at.

`python -m fusion.serve --snapshots <dir>` serves saved snapshots.
`python -m fusion.serve --live oracles/sources.toml` fetches live.

## Rules

- **Clean room.** This project is new and standalone. Build only from this spec,
  SCENARIO.md, the providers' public documentation, and what the real
  servers actually return.
- Fake data only. Credentials are fake and live in `oracles/.env`
  (gitignored). Never print them.
- Tests in `tests/` are network-free. `uv run pytest` must be green.
  Oracles are opt-in scripts, not collected by pytest (not named `test_*`).
- Plain functions and dataclasses. Mark each deliberate shortcut with a
  `# ponytail:` comment naming the limit and the upgrade path.
