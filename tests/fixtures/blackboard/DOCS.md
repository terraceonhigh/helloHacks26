# Blackboard Learn — what was checked against vendor docs

`lauds/adapters/blackboard.py` is a clean port of main's `hub/blackboard.py`,
whose own module docstring is explicit: **"EVERYTHING IN THIS MODULE IS AN
INFORMED HYPOTHESIS, NOT A CONFIRMED FACT"** — no Blackboard tenant has ever
existed on this project, at UBC or anywhere. This task's job was to check
that hypothesis against the vendor's own **published** docs (no sandbox
signed up for, per BRIEF.md) and report exactly how far that got — not to
promote it to "verified" on the strength of a doc mention alone.

## What was checked, and how

- **`https://developer.blackboard.com/portal/displayApi`** — the Learn REST
  API reference portal. Fetched directly: the page is a JS-rendered Swagger/
  API-explorer shell, so a plain page fetch returns only the header/nav, not
  the endpoint definitions or example bodies themselves (confirmed by
  fetching it and getting no API content back — this is a tooling
  limitation of this session, not a claim that the portal lacks the
  information).
- **`docs.anthology.com/docs/blackboard/rest-apis/...`** (Anthology's own
  developer-docs site, Blackboard's parent company) — several specific
  hands-on/reference pages returned **HTTP 404** when fetched directly
  (`rest-api-best-practices`, `getting-started/framework`,
  `hands-on/pulling-gradebook-data-and-assessment-grades`), even though a web
  search surfaced them as titles — the site is also JS-routed, so a direct
  fetch of a deep link 404s outside the SPA shell. Search-engine snippets
  *of* those pages (not a page fetch I can quote verbatim, so treated as
  weaker evidence than a direct fetch) describe a Course object with
  properties `externalId`, `courseId`, `name`, `description`, `allowGuests`,
  `readOnly`, `termId`, `dataSourceId`, and confirm both `GET
  /learn/api/public/v1/courses/{id}` (primary key, e.g. `_1_1`) and `GET
  /learn/api/public/v1/courses/externalId:<value>` addressing forms.
- No fetch or search turned up a full, literal worked-example JSON response
  body for `GET /learn/api/public/v1/users/{userId}/courses` (the
  `Course Memberships for User` list, with its `paging.nextPage` field) or
  for `GET /learn/api/public/v1/courses/{courseId}?expand=term` (whether
  `?expand=term` embeds a `term: {"name": ...}` object, as `to_course()`
  assumes, or something else) — only schema-level field-name mentions, never
  a response body to actually compare `to_course()`'s output against.

## Result

**Grade: fixture-only** (unchanged from main). The `courseId`/`id`/
`externalId` field-naming and the primary-key-vs-`externalId:` addressing
convention are corroborated at the schema-property level by Anthology's own
docs (search snippets of pages this session couldn't fetch directly), which
is consistent with `to_course()`'s mapping — but "a field name is mentioned
in a schema" is not "a published example was matched" (BRIEF.md's bar for
`docs-verified`), especially for the two things this adapter most needs
confirmed and didn't find: the list response's `paging`/`nextPage` shape,
and whether `?expand=term` really nests `{"name": ...}` under `term`. Both
remain exactly the same **unverified hypothesis** main's own docstring
already flagged, carried over unchanged into this port.

No `tools/harvest_docs.py` fixture was added: nothing fetched here was a
literal vendor-published example payload distinct from what
`tests/fixtures/blackboard/parse_capture.json` /
`tests/fixtures/blackboard/to_course_no_term.json` (already-existing,
hand-built-but-doc-informed fixtures) cover — there was no real example to
harvest through main's parser.
