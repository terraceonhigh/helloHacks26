"""Blackboard Learn (Ultra) adapter: browser-session login (hub.site), then
Blackboard's own public REST API (`/learn/api/public/v1/...`) for courses.

**[unverified] EVERYTHING IN THIS MODULE IS AN INFORMED HYPOTHESIS, NOT A
CONFIRMED FACT.** UBC does not run Blackboard -- it runs Canvas (and, per
hub/brightspace.py, at least one course also happens to run through
Brightspace) -- so there is no UBC Blackboard instance, and no Blackboard
account anywhere on this project, to test any of this against. Nothing below
has ever been run against a live Blackboard tenant.

Why this isn't just "scrape the page" or "give up", the way a first-draft
adapter for an untestable site normally would:

- Blackboard's *official* integration path -- an admin-issued application ID
  ("App Key/Secret") registered via REST API Integrations, then 3-legged
  OAuth2 -- needs an institution admin, same blocker as Workday and (this
  project previously assumed) Brightspace. That row in
  docs/api-standards.md ("App key plus admin-added integration... No") is
  correct and this module does not contradict it.
- But hub/brightspace.py found that the *official*, admin-gated developer
  program is not the only way in: a plain logged-in browser session reaches
  Brightspace's own `/d2l/api/lp/...` REST endpoints directly, with no
  developer key at all, because that's genuinely what the Ultra-equivalent
  Brightspace web UI itself calls to render the page. That was a real,
  **verified** finding (Terrace, 2026-09-26, against a real UBC course).
- Blackboard Learn Ultra is architecturally the same shape: a React/Ultra
  single-page frontend that Blackboard's own developer documentation
  (developer.blackboard.com / `docs.blackboard.com/rest-apis/learn`)
  confirms is backed by exactly this REST API -- `/learn/api/public/v1/...`,
  versioned `v1`/`v2`/`v3` per resource, documented resources including
  Users, Course Memberships, Courses, Course Contents, Calendars,
  Announcements and Gradebook. The **hypothesis** this module encodes is
  that the Ultra web UI calls these same public, documented paths with just
  its own session cookie -- the same pattern Brightspace's Ultra-equivalent
  UI turned out to use -- rather than needing the separate OAuth app-key
  flow. That is a reasonable inference from Blackboard's own docs plus the
  Brightspace precedent, **not a confirmed fact**: nobody has opened a
  Network tab on a real Blackboard Ultra course to check what the page
  actually calls. Treat every endpoint below as "documented to exist, and
  plausibly session-cookie-reachable" -- not "known to work".

Documented (developer.blackboard.com) endpoints this hypothesis rests on:
- `GET /learn/api/public/v1/users/me` -- several Blackboard SaaS releases
  document a `me` alias for the calling user on the Users resource (the
  same idea as Brightspace's `users/whoami`); whether the specific tenant
  version this would run against actually supports the literal `me` alias,
  versus needing a real user ID, is unconfirmed. Used here only to confirm
  the session is live and to read the caller's own `id`.
- `GET /learn/api/public/v1/users/{userId}/courses` -- the documented
  "Course Memberships for User" resource: one membership object per course
  the user is enrolled in, each carrying a `courseId` (Blackboard's
  internal course primary key, not the human-readable code) and a
  `courseRoleId`. Paginated via the standard Blackboard list shape
  (`{"results": [...], "paging": {"nextPage": "..."}}`), followed here the
  same way hub/brightspace.py follows D2L's own bookmark cursor.
- `GET /learn/api/public/v1/courses/{courseId}?expand=term` -- the
  documented Courses resource, keyed by that internal id. `courseId` here
  is the *human* course code (e.g. "BIOL101.2026FA"), `name` is the title,
  and `?expand=term` is documented to embed the Term resource (`name`)
  inline so this doesn't need a second round trip per course. Whether
  `expand=term` is honoured by every tenant version is unconfirmed; the
  parser below tolerates its absence and just leaves `term` blank.

**Items (due dates): not built here, on purpose -- the exact same honest gap
hub/brightspace.py documents.** This project's rule for any site behind a
login is: read its JSON, never its rendered page HTML. Blackboard's docs do
describe a `GET /learn/api/public/v1/calendars` resource, but every
description of it (and of the "Calendar" concept elsewhere in the docs)
describes *calendar objects* (a course calendar's id/name/type), not a
feed of dated events/due items -- there is no confirmed, documented
"list this course's upcoming due dates as JSON" endpoint anywhere in the
public v1/v2/v3 docs consulted. (The Gradebook Column resource does
document a `grading.due` timestamp field, which is a *plausible* future
source of due dates -- but nobody has confirmed it is populated the way a
student dashboard would need, and pulling grade-column data just to get due
dates is a bigger, separate design decision.) Rather than fill that gap by
scraping Ultra's rendered HTML -- which this project's rule (and this exact
module's own reasoning above for why JSON-over-HTML matters) says not to do
-- `fetch()` below returns real (well: hypothesised-real) courses and an
empty item list, exactly like hub/brightspace.py does for its own
unconfirmed calendar gap. Whether to chase the Gradebook `grading.due`
field, or to grant Ultra HTML an explicit scrape exception the way
PrairieLearn/WeBWorK have one (neither has any JSON API at all, unlike
here), is a call for Jacky/the team -- not something this file resolves.

Blackboard is multi-tenant like Brightspace (every institution runs its own
subdomain, e.g. `blackboard.<school>.edu`, not a single shared host) -- so
`base` is always an explicit argument here, never a module-level constant.

Try it (will fail without a real Blackboard instance and login):
  uv run python -m hub.blackboard <base-url>
"""
from hub import site
from hub.models import Course

SITE = "blackboard"


def login(base):
    """Open a visible browser at `base`; the student signs in through
    whatever SSO that institution fronts Blackboard with; save the session.
    [unverified]: never tried against a real Blackboard login page, so the
    "logged in = back on `base` past /login" check hub.site.login makes is
    an assumption carried over from Canvas/Brightspace, not a confirmed fact
    for Blackboard's own redirect chain."""
    site.login(SITE, base)


def _get_json(req, base, path):
    r = req.get(f"{base}{path}")
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return r.json()


def next_page(page):
    """Blackboard's documented list-response shape is
    `{"results": [...], "paging": {"nextPage": "/learn/api/public/v1/...&offset=N"}}`.
    Returns that relative path, or None once there isn't one -- the JSON
    equivalent of hub.site.next_link's Link-header parsing, and of
    hub/brightspace.py's Bookmark/HasMoreItems cursor, for this API's own
    documented paging convention. [unverified] end-to-end since it's never
    seen a real Blackboard response, but this exact shape (a `paging` object
    carrying a ready-to-use `nextPage` path) is what Blackboard's own REST
    API docs describe for every list resource."""
    return (page.get("paging") or {}).get("nextPage")


def _get_all(req, base, path):
    """GET `path`, following `next_page` until Blackboard says there isn't
    one. Returns the concatenated `results` list."""
    out = []
    while path:
        page = _get_json(req, base, path)
        out += page.get("results", [])
        path = next_page(page)
    return out


def to_course(course):
    """One Blackboard Courses resource object -> a Course. `courseId` is the
    *human-readable* code (Blackboard's own docs distinguish it from the
    internal `id` primary key used in URLs), `name` is the title.
    `?expand=term` is documented to nest a Term resource under `term`; if a
    tenant doesn't honour that (or the field is simply absent), `term` is
    left blank rather than guessed -- same defensive shape
    hub/brightspace.py uses for its own "no separate section/term field"
    gap. There is no documented per-student "section" distinct from the
    course itself in the resources this module reads, so `section` is
    always left blank too."""
    return Course(
        code=course.get("courseId") or course.get("id", ""),
        section="",
        term=(course.get("term") or {}).get("name", ""),
        title=course.get("name", ""),
    )


def _courses(req, base, user_id):
    memberships = _get_all(req, base, f"/learn/api/public/v1/users/{user_id}/courses")
    courses = []
    for m in memberships:
        course_id = m.get("courseId")
        if not course_id:
            continue  # malformed membership row; skip rather than guess an id
        courses.append(to_course(_get_json(req, base, f"/learn/api/public/v1/courses/{course_id}?expand=term")))
    return courses


def _run(req, base):
    # [unverified] `me` alias - see module docstring. Also doubles as the
    # "confirm the session is actually live" check hub/brightspace.py's
    # whoami call makes.
    me = _get_json(req, base, "/learn/api/public/v1/users/me")
    courses = _courses(req, base, me["id"])
    return courses, []  # see module docstring: no confirmed JSON endpoint for due dates


def fetch(base):
    """Return (courses, items) for the student's Blackboard course
    memberships. `items` is always `[]` today -- see the module docstring's
    "Items" section for why. Opens a browser window to log in if there's no
    saved session.

    [unverified] end to end: no real Blackboard instance has ever answered
    these requests. A login failure, an unexpected response shape, or any
    other exception returns ([], []) rather than crashing the dashboard
    (AGENTS.md "handle failure without crashing the dashboard")."""
    try:
        return site.fetch_with_session(SITE, base, lambda req: _run(req, base))
    except Exception:
        return [], []


if __name__ == "__main__":
    import sys

    from hub import db

    if len(sys.argv) < 2:
        print("usage: uv run python -m hub.blackboard <base-url>")
        raise SystemExit(1)
    courses, items = fetch(sys.argv[1])
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:30} {c.title}")
    if not items:
        print("\n(no items yet -- see hub/blackboard.py's module docstring)")
