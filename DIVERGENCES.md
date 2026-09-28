# Divergences from the oracle

The parity comparator (`tests/parity/superset.py`) fails on any difference
between main's output (a golden under `tests/oracle/`) and lauds' output,
**unless** that exact difference is listed in the JSON block below. It also
fails on a listed divergence that no comparison needed (no stale excuses).

A divergence is allowed only with **evidence**: a raw fixture or a recorded
live payload that shows the oracle was wrong (BRIEF.md, rule 5). "I think it
was wrong" isn't evidence. Never edit a golden to make a test pass.

## How to add one

Append an object to the list in the block. Every field is required:

| field | what |
|---|---|
| `adapter` | the golden's `adapter` (`"queries"` for query goldens) |
| `case` | the golden's `case` (its file name without `.json`) |
| `key` | the record's identity as a JSON list, exactly as the failure message prints it (items `[source, url]`; courses `[code, section, term]`; textbooks `[course, isbn]`; meetings `[course, kind, [days], start_time, term_start, source]`; query rows use their query's key, e.g. upcoming `[source, url]`) |
| `field` | the differing field, or `"*"` for a record lauds doesn't emit at all |
| `oracle` | the oracle's value, exactly (for `"*"`: the whole oracle record) |
| `new` | lauds' value after `lauds.compat.to_main`, exactly (for `"*"`: `null`) |
| `evidence` | path (or list of paths), relative to the repo root, of the fixture/payload proving the oracle wrong; must exist |
| `reason` | one or two sentences: what the evidence shows and why the new value is right |

Example (not live - shown outside the block):

    {"adapter": "webwork", "case": "live_fake101", "key": ["webwork", "http://host/webwork2/fake101/hw1/"],
     "field": "due", "oracle": "2026-10-01T23:59:00-08:00", "new": "2026-10-01T23:59:00-07:00",
     "evidence": "tests/fixtures/webwork/live_fake101_sets.html",
     "reason": "The page says PDT; main mapped every abbreviation to PST."}

## The list

```json
[]
```
