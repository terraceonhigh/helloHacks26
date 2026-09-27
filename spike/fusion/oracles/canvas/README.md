# Canvas: no oracle server (SYNTHETIC fixtures only)

Canvas has no published Docker image, and a source build (Rails + Postgres +
Redis + asset compile) doesn't fit the shared spike machine. So there's **no live
server, no fake fstudent account and no secrets** for Canvas. The adapter
(`fusion/adapters/canvas.py`) and its fixtures (`fixtures/canvas/`) are authored
from Canvas's public REST API docs and are **unverified against a live Canvas**.

- `up.sh`: there's nothing to bring up. It only regenerates
  `fixtures/snapshots/canvas.json` from the fixtures (idempotent).
- `login.py`: `login(base, secrets)` builds a `requests.Session` from a
  browser-captured `CANVAS_COOKIE` (the SSO path) or a `CANVAS_TOKEN` in
  `secrets.env` (gitignored). With neither it raises, so run.py reports Canvas
  as an error in `/health`, or you replay the snapshot instead.
- Down: nothing to stop.
- To replace the PrairieLearn placeholder link in C1, see `fixtures/canvas/README.md`
  (the `PL_QUIZ1_URL` constant).

## Canvas behaviour the adapter handles (from the docs, plus known behaviour flagged)

1. **`while(1);` prefix.** Canvas prepends it to JSON served to a cookie
   session, as an anti-JSON-hijacking guard. It's stripped when present. Token
   sessions don't get it. *Known behaviour, not found in the current docs text.*
2. **Link-header pagination.** Every list is paginated (10 per page by default,
   with an unspecified `per_page` cap). Follow `rel="next"`. The links are opaque
   absolute URLs that already carry every parameter, so don't re-send params.
   Match the header name case-insensitively. `rel="last"` may be missing. The
   planner uses `page=bookmark:<base64>` cursors.
3. **Planner window.** `/api/v1/planner/items` needs `start_date`/`end_date`.
   The adapter uses the union of the student's term dates (`include[]=term`).
   Concluded courses are left out of the planner unless asked for.
4. **The planner has no body for assignments.** The planner's `plannable` for an
   assignment carries title/due/points but no `description`, so the adapter
   fetches `/api/v1/courses/:c/assignments/:id` for links_out (and `unlock_at`).
   Quizzes and discussions/announcements work the same way (`/quizzes/:id`,
   `/discussion_topics/:id` `message`).
5. **Times are UTC `Z`** in the API. Canvas's "11:59pm" due is `23:59:59` local.
6. **`plannable_date`** is the planner's date for any type. Announcements
   use their post date there, so they get no due. *`plannable_date` isn't in the
   docs' example response, though Canvas returns it.*
7. **done** comes from `submissions.submitted` or `excused`, or
   `planner_override.marked_complete`. `submissions: false` means there's no
   assignment behind the item, so done is `None`.
8. **`html_url` can be relative** (`/courses/1/assignments/2`) or absolute. It's
   absolutized against base.
9. **External-tool assignments** (`submission_types: ["external_tool"]`) are
   submitted in the tool. The tool's LTI launch URL
   (`external_tool_tag_attributes.url`) is *not* the tool's item page, so it isn't
   used. The description's links to the tool's item page are the fusion evidence.
10. Access-restricted courses come back with only `id` + `name`, so the label falls
    back to the name. Group and personal (planner note) items get a stand-in course
    the fusion core won't resolve (with a note).
