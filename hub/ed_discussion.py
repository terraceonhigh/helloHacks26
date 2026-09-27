"""Ed Discussion (edstem.org) adapter: personal API token -> plain REST JSON.

Ed is a Q&A/discussion board many CS/STEM courses run alongside Canvas --
it is not a due-date tracker, and this module doesn't pretend otherwise.
See "What this returns" below for exactly what is real vs. reasoned vs.
left as an honest gap.

## What's real, and where it came from

docs/api-standards.md already flagged Ed as "Personal API token; undocumented
API (edapi)". Before writing anything here, the actual `edapi` source was
cloned and read (not just its PyPI description):

    git clone https://github.com/smartspot2/edapi   (maintainer: smartspot2)
    https://pypi.org/project/edapi/

Confirmed by reading `edapi/edapi.py` and `edapi/types/api_types/*.py` in
that clone (not paraphrased from memory or the README):

- **Auth is a personal API token**, obtained by the student themselves at
  https://edstem.org/us/settings/api-tokens (edapi.py's own `AUTH_MESSAGE`
  constant points there). It is sent as `Authorization: Bearer <token>`
  (edapi.py's `EdAPI._auth_header` property, ~line 169-174) -- no OAuth, no
  admin involvement, matching this project's Canvas-PAT-style pattern
  exactly, and matching how Ed's own accessibility/help docs describe a
  student obtaining their own token.
- **API base is `https://us.edstem.org/api/`** (edapi.py `API_BASE_URL`,
  line 37). Ed's student-facing web app itself lives at
  `https://edstem.org/us/...` (confirmed real by e.g. Yale's help page on
  linking a discussion category: "Ed Discussion site URLs should look
  similar to: https://edstem.org/us/courses/1234/discussion/" --
  https://help.canvas.yale.edu/a/1544915) -- the API host (`us.edstem.org`)
  and the web host (`edstem.org/us`) are different, both real.
- **"My courses" is real and date-free by nature, not by omission.**
  `EdAPI.get_user_info()` (edapi.py ~line 182-192) calls `GET /api/user`
  and returns `courses: list[API_User_Response_Course]`
  (types/api_types/endpoints/user.py ~line 16-29), each wrapping an
  `API_Course` (types/api_types/course.py ~line 11-27) with real fields
  `id`, `code`, `name`, `year`, `session`, `status` ("archived" or
  "active"). That's the whole shape -- there's no term-dates field here
  either, just a course, its code/name and an active/archived flag.
- **Threads are real, and were read in full -- no due-date-shaped field
  exists anywhere on one.** `EdAPI.list_threads(course_id, ...)`
  (edapi.py ~line 233-256) calls `GET /api/courses/<course_id>/threads`
  and returns `API_ListThreads_Response["threads"]`
  (types/api_types/endpoints/threads.py ~line 29-36), each a
  `API_Thread_WithUser` (types/api_types/thread.py ~line 11-77). The full
  `API_Thread` TypedDict was read field-by-field: `id` ("global post
  number"), `course_id`, `number` ("post number relative to the course"),
  `type` (a plain string -- `edapi/constants.py`'s `ThreadType` names the
  real values seen: `"post"`, `"question"`, `"announcement"`), `title`,
  `content`/`document` (free-text/XML thread body, "rendered version of
  content"), `category`/`subcategory`/`subsubcategory` (free-text,
  **instructor-defined discussion categories like "General" or
  "Assignment 1" -- NOT a date or deadline category, don't confuse this
  with `hub.models.category_for`**), `is_pinned`/`pinned_at`,
  `is_locked`/`is_answered`/`is_archived`/etc., `created_at`/`updated_at`
  (post timestamps -- when the thread was written or last touched, not a
  deadline). **There is no `due`, `deadline`, `date`, or any other
  date-shaped field on a thread anywhere in this type.** So per this task's
  own instructions ("if genuinely nothing date-shaped exists in the real
  API, return courses only... rather than inventing a due-date source that
  isn't real"), `fetch()` below never sets `Item.due` to anything but
  `None` -- there is nothing real to put there.

## What's reasoned by analogy, not confirmed by edapi itself

- **A per-thread web URL.** `edapi`'s own client never constructs one (it
  only calls the API); the one confirmed real web URL shape is the
  *course* discussion page, `https://edstem.org/us/courses/<id>/discussion/`
  (cited above, Yale help page). This module reasons that a specific
  thread's real deep link appends the thread's own id --
  `https://edstem.org/us/courses/<course_id>/discussion/<thread_id>` -- by
  analogy to that confirmed course-level pattern and to how every other
  numeric-id-in-the-path Ed API endpoint works (`threads/<thread_id>`,
  `courses/<id>/threads/<number>`). This is the one part of this module
  that is reasoned, not read verbatim from a citable source -- flagged
  here loudly rather than silently assumed. It does not affect correctness
  of `hub.db`'s `UNIQUE(source, url)`: `thread["id"]` is real, described in
  the type itself as a "global post number" unique across all of Ed, so
  the constructed URL is unique per thread even if Ed's own web app were to
  route it slightly differently.
- **`term`** is built by joining a course's real `year` and `session`
  fields (e.g. `"2026"` + some session code) -- both fields are confirmed
  real (course.py), but the exact string Ed puts in `session` (a term
  code? a name?) was never seen in a live response, so this is a
  best-effort join, not a confirmed format like Canvas's `"2026 Winter
  Term 1"`.

## Scope actually built

Given all of the above, this adapter does the honest middle ground the
task called for: real courses (from every non-archived entry in `GET
/api/user`'s `courses` list), plus **undated** `Item`s for the threads
that are Ed's own real "this matters more than an ordinary post" signal --
pinned threads (`is_pinned`) and instructor announcements
(`type == "announcement"`). Every such Item gets `due=None`. This mirrors
how `hub/canvas.py` already treats Canvas announcements (real,
`kind="announcement"`, `due=None` -- see its `to_item`/`done_from_submissions`
comments) rather than a new invented category. An ordinary Q&A thread
(`type == "post"`/`"question"`, not pinned) is not surfaced as an Item --
those are just discussion, not the "what do I need to do this week" signal
this project is for.

No LLM-based free-text date extraction (the pattern `hub/syllabus.py` uses
for Canvas announcements/PDFs) is attempted here: that would need a second
credential (the student's own Anthropic key) this task never asked for, and
risks exactly the "confident but wrong date" failure mode AGENTS.md's
"handle failure without crashing" rule warns about. If a human later wants
real exam dates out of pinned Ed threads' free text, that LLM-extraction
step belongs next to `hub/syllabus.py`'s, not duplicated here.

Try it:  ED_DISCUSSION_TOKEN=<your token> uv run python -m hub.ed_discussion
"""
import os

import requests

from hub.models import Course, Item, category_for

API_BASE = "https://us.edstem.org/api/"
WEB_BASE = "https://edstem.org/us"
SOURCE = "ed_discussion"

# Real values, from edapi/constants.py's ThreadType (cited in the module
# docstring): a thread's `type` field is one of these three strings.
ANNOUNCEMENT_TYPE = "announcement"


class AuthError(Exception):
    """Ed rejected this API token (401). Distinct from a network/shape
    error so a caller can tell "bad token" from "Ed is down"."""


def _get_json(session, path, **params):
    r = session.get(API_BASE + path, params=params or None, timeout=15)
    if r.status_code == 401:
        raise AuthError("Ed Discussion rejected this API token")
    r.raise_for_status()
    return r.json()


def to_course(entry):
    """One entry of `GET /api/user`'s real `courses` list -> a Course.
    `entry["course"]` is the real `API_Course` shape (id/code/name/year/
    session/status) -- see module docstring. `term` joins the two real
    date-ish fields Ed provides; that join's exact spelling is reasoned,
    not confirmed (see module docstring)."""
    c = entry["course"]
    term = " ".join(part for part in (c.get("year") or "", c.get("session") or "") if part)
    return Course(code=c.get("code", ""), section="", term=term, title=c.get("name", ""))


def is_deadline_relevant(thread):
    """Ed's own real "more than an ordinary post" signals: pinned by
    staff, or a genuine announcement. See module docstring for why this
    (not a keyword search, not an invented "category") is the honest line
    to draw with the real fields a thread actually has."""
    return bool(thread.get("is_pinned")) or thread.get("type") == ANNOUNCEMENT_TYPE


def to_item(thread, course_code):
    """One real `API_Thread`(_WithUser) -> an undated Item. `due` is always
    `None`: there is no date-shaped field on a real Ed thread to read one
    from (see module docstring). `url` is reasoned-by-analogy, not a field
    Ed's API returns -- but `thread["id"]` ("global post number", real and
    unique across all of Ed) makes it unique regardless of whether Ed's
    web app routes it exactly this way."""
    return Item(
        course=course_code,
        category=category_for("announcement"),
        kind="announcement",
        title=thread.get("title", ""),
        due=None,
        url=f"{WEB_BASE}/courses/{thread['course_id']}/discussion/{thread['id']}",
        source=SOURCE,
        done=None,
    )


def _run(session):
    user_info = _get_json(session, "user")
    courses = []
    items = []
    for entry in user_info.get("courses", []):
        if entry.get("course", {}).get("status") == "archived":
            continue
        course = to_course(entry)
        courses.append(course)
        course_id = entry["course"]["id"]
        try:
            threads_resp = _get_json(session, f"courses/{course_id}/threads", limit=30, sort="new")
        except Exception:
            # One course's threads failing (e.g. discussion disabled for it)
            # shouldn't drop every other course's data -- AGENTS.md "handle
            # failure without crashing the dashboard".
            continue
        for thread in threads_resp.get("threads", []):
            if is_deadline_relevant(thread):
                items.append(to_item(thread, course.code))
    return courses, items


def fetch(token):
    """Return (courses, items) for the student's own Ed Discussion account.

    `token` is the student's own personal API token (see module docstring
    for where they get one) -- passed in explicitly by the caller, never
    read from an env var or hardcoded here (this project's rule for every
    credential; see AGENTS.md rule 3 and every other adapter in hub/).

    A bad token, a network error, or an unexpected response shape returns
    `([], [])` rather than crashing the dashboard (AGENTS.md "handle
    failure without crashing").
    """
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    try:
        return _run(session)
    except Exception:
        return [], []


if __name__ == "__main__":
    from hub import db

    token = os.environ.get("ED_DISCUSSION_TOKEN")
    if not token:
        print("usage: ED_DISCUSSION_TOKEN=<your Ed API token> uv run python -m hub.ed_discussion")
        print("Get a token at https://edstem.org/us/settings/api-tokens")
        raise SystemExit(1)
    courses, items = fetch(token)
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:20} {c.title}")
    for i in items:
        print(f"  [{i.kind}] {i.course}: {i.title}")
    if not items:
        print("\n(no pinned/announcement threads found -- see hub/ed_discussion.py's module docstring)")
