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
[
{
  "adapter": "queries",
  "case": "done_clobbered_by_a_later_unknown_write",
  "key": [
    "result"
  ],
  "field": "*",
  "oracle": {
    "now_a": {
      "by_course": {
        "CPSC 121": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            null,
            "canvas"
          ]
        ]
      },
      "courses": [
        [
          "CPSC 121",
          "2026W1",
          "Models of Computation",
          88.5
        ]
      ],
      "now": "2026-09-28T09:00:00-07:00",
      "schedule": [],
      "status_of_upcoming": [
        "soon"
      ],
      "textbooks": [],
      "undated": [],
      "upcoming": [
        [
          "CPSC 121",
          "task",
          "quiz",
          "Quiz 2",
          "2026-09-30T06:59:00+00:00",
          "https://x/q/1",
          null,
          "canvas"
        ]
      ],
      "upcoming_by_category": {
        "deadline": [],
        "material": [],
        "task": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            null,
            "canvas"
          ]
        ]
      }
    },
    "now_b": {
      "by_course": {
        "CPSC 121": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            null,
            "canvas"
          ]
        ]
      },
      "courses": [
        [
          "CPSC 121",
          "2026W1",
          "Models of Computation",
          88.5
        ]
      ],
      "now": "2026-11-15T09:00:00-08:00",
      "schedule": [],
      "status_of_upcoming": [
        "overdue"
      ],
      "textbooks": [],
      "undated": [],
      "upcoming": [
        [
          "CPSC 121",
          "task",
          "quiz",
          "Quiz 2",
          "2026-09-30T06:59:00+00:00",
          "https://x/q/1",
          null,
          "canvas"
        ]
      ],
      "upcoming_by_category": {
        "deadline": [],
        "material": [],
        "task": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            null,
            "canvas"
          ]
        ]
      }
    }
  },
  "new": {
    "now_a": {
      "by_course": {
        "CPSC 121": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            1,
            "canvas"
          ]
        ]
      },
      "courses": [
        [
          "CPSC 121",
          "2026W1",
          "Models of Computation",
          88.5
        ]
      ],
      "now": "2026-09-28T09:00:00-07:00",
      "schedule": [],
      "status_of_upcoming": [
        "done"
      ],
      "textbooks": [],
      "undated": [],
      "upcoming": [
        [
          "CPSC 121",
          "task",
          "quiz",
          "Quiz 2",
          "2026-09-30T06:59:00+00:00",
          "https://x/q/1",
          1,
          "canvas"
        ]
      ],
      "upcoming_by_category": {
        "deadline": [],
        "material": [],
        "task": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            1,
            "canvas"
          ]
        ]
      }
    },
    "now_b": {
      "by_course": {
        "CPSC 121": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            1,
            "canvas"
          ]
        ]
      },
      "courses": [
        [
          "CPSC 121",
          "2026W1",
          "Models of Computation",
          88.5
        ]
      ],
      "now": "2026-11-15T09:00:00-08:00",
      "schedule": [],
      "status_of_upcoming": [
        "done"
      ],
      "textbooks": [],
      "undated": [],
      "upcoming": [
        [
          "CPSC 121",
          "task",
          "quiz",
          "Quiz 2",
          "2026-09-30T06:59:00+00:00",
          "https://x/q/1",
          1,
          "canvas"
        ]
      ],
      "upcoming_by_category": {
        "deadline": [],
        "material": [],
        "task": [
          [
            "CPSC 121",
            "task",
            "quiz",
            "Quiz 2",
            "2026-09-30T06:59:00+00:00",
            "https://x/q/1",
            1,
            "canvas"
          ]
        ]
      }
    }
  },
  "evidence": "tests/oracle/queries/done_clobbered_by_a_later_unknown_write.json",
  "reason": "main's own upsert (hub/db.py: \"done=excluded.done\", unconditional) lets a second, less-informed write to the same (source, url) - e.g. Canvas's .ics feed re-saving a quiz with no completion signal at all - silently erase an earlier done=True, live-verified by replaying this exact seed through the oracle's own hub.db.save/upcoming/status_of (the cited golden). lauds' store.py now does done=COALESCE(excluded.done, done): a write that genuinely doesn't know completion (done=None) never clears a previously-known one."
}
]
```
