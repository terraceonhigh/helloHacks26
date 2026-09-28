# Brightspace (D2L Valence) — what was checked against vendor docs

`lauds/adapters/brightspace.py` is a clean port of main's `hub/brightspace.py`.
Main's own module docstring cites a live check (Terrace, 2026-09-26, against
a real UBC course on `ubc.brightspace.com`), and
`tests/fixtures/brightspace/myenrollments_items.json` /
`tests/oracle/brightspace/to_course_mapping.json` are that real, anonymised
response shape reused as a fixture — but that check was main's, not this
port's own (BRIEF major finding: repeating another project's live-verified
claim as if this branch had run it itself is exactly the overclaiming that
finding is about; see `lauds/adapters/brightspace.py`'s own docstring for the
correction). This file adds a second, independent check against D2L's
**published** Valence API docs (no sandbox signed up for, per BRIEF.md), to
corroborate the same shape from the vendor's own reference — this file's own
"docs-verified" conclusion stands on its own regardless of that grading fix.

## What was fetched and quoted

- **`https://docs.valence.desire2learn.com/basic/apicall.html`** (Brightspace
  API calling conventions) — the general paged-result-set wrapper every
  Valence "List" action (including `myenrollments`) returns:

  ```json
  "PagingInfo": {
     "Bookmark": <string>,
     "HasMoreItems": <boolean>
  }
  ```
  wrapped as `Api.PagedResultSet { "PagingInfo": {...}, "Items": [...] }`.
  `Bookmark`: "an opaque string value identifying the last item in the
  returned segment" (query param on the next call); `HasMoreItems`: false
  once no more pages remain. **This matches `lauds/adapters/brightspace.py`'s
  `_enrollments()` exactly**: it reads `page.get("PagingInfo", {})`,
  `.get("HasMoreItems")` and `.get("Bookmark")`, and appends `&bookmark=...`
  for the next call — same field names, same stop condition.

- **`https://docs.valence.desire2learn.com/res/enroll.html`** (the
  `myenrollments` action's own reference page) — confirms the `MyOrgUnitInfo`
  data block's `OrgUnit` sub-object carries `Id`, `Type`, `Name`, `Code`,
  `HomeUrl`, `ImageUrl` (no separate section/term field — matches
  `to_course()`'s comment that section/term are left blank, not guessed), an
  `Access` object, and a `PinDate`. The page describes the block's *shape*
  (property list) but does not itself show a full worked example with
  literal field values for this specific action.

## Result

**Grade for this port: docs-verified** (not live-verified — see the
correction above; main's own account is live-verified, this port's is not,
until a real `tests/live/brightspace_live.py` three-way check exists). The
Valence docs check above is an independent corroboration of the same field
names and the same paging mechanism, from the vendor's own reference — it
found nothing that contradicts main's live-tested mapping, and needed no
code change.

No `tools/harvest_docs.py` fixture was added: the pages found are schema/
field-shape references (types and property names, e.g. `Bookmark: <string>`),
not a single worked example payload with literal values distinct from what
`tests/fixtures/brightspace/myenrollments_items.json` (the real, already-
verified capture) already covers — fabricating a synthetic "doc example" from
a type table would not be a genuine vendor-published example, so none was
invented.
