"""Brightspace (D2L) adapter: browser-session login (lauds.session), then the
site's own JSON endpoints for course enrollments. Clean port of main's
hub/brightspace.py - same verified endpoints, same "items always []" gap,
rewritten against lauds' plugin protocol (pure parse functions + fetch via
lauds.session, no swallow-to-([],[]) - lauds.sync isolates one broken
adapter from the rest, see lauds/sync.py:sync_one).

**Endpoint shape, cited from main's own docstring** (Terrace, 2026-09-26, a
real UBC course on ubc.brightspace.com - UBC's main LMS is Canvas; this one
course happens to also run through Brightspace too):

- `GET /d2l/api/lp/unstable/users/whoami` confirms the session is live.
- `GET /d2l/api/lp/1.50/enrollments/myenrollments/?orgUnitTypeId=3&isActive=true&canAccess=true`
  returns the student's own active enrollments as JSON, paginated via D2L's
  documented `PagingInfo` cursor (`Bookmark`/`HasMoreItems`).

**Grade for THIS port: fixture-only, not live-verified** (BRIEF major
finding) - the line above is main's own live check, not one this branch
ran itself: there is no `tests/live/brightspace_live.py`, and this
adapter's only golden (`to_course_mapping`) replays a fixture, never a
live payload. Repeating main's claim here as if it were this port's own
verification is exactly the overclaiming that finding calls out; don't
re-add it without a real three-way check backing it (see
`tests/live/webwork_live.py`'s docstring for the pattern).

**Items (due dates): not built here, on purpose** - same as main. Brightspace's
own Calendar screens are built from an older format that isn't plain JSON and
isn't meant to be read by other programs; no separate documented JSON
due-date endpoint turned up while testing live. `fetch()` returns real
courses and an empty item list rather than scrape that rendered page (this
project's rule for anything behind a login: read JSON, never rendered HTML).

Brightspace is multi-tenant (every institution runs its own subdomain/custom
domain) - `base` is always an explicit argument, never a module constant, and
may be a bare origin or a full course URL (`_origin` normalises either).

Try it:  uv run python -m lauds.cli sync brightspace
"""
import json
from urllib.parse import urlsplit

from lauds import session
from lauds.models import Bundle, Course

NAME = "brightspace"
DESCRIPTION = "Brightspace (D2L): course enrollments (no due-date feed found yet)"

MYENROLLMENTS = "/d2l/api/lp/1.50/enrollments/myenrollments/?orgUnitTypeId=3&isActive=true&canAccess=true"


def _origin(base: str) -> str:
    """Normalise `base` to just scheme://host, whether it's a bare origin or
    a full course URL (e.g. ".../d2l/home/7067", the natural thing to paste
    when signing in on your own course page) - every `/d2l/api/...` path
    below is absolute from the origin, so a full course URL left un-normalised
    would build a broken, doubled-up URL."""
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


def login(base: str) -> None:
    """Open a visible browser at `base`'s origin; the student signs in
    through whatever SSO that institution fronts Brightspace with."""
    session.login(NAME, _origin(base))


def to_course(enrollment: dict) -> Course:
    """One entry of `enrollments/myenrollments`'s real `Items` list -> a
    Course. `OrgUnit.Code` is the real, verified `code` shape (e.g.
    "MATH_V 100A ALL SECTIONS 2026W1"); there's no separate section/term
    field in this response, so those are left blank rather than guessed by
    splitting the code text."""
    org_unit = enrollment["OrgUnit"]
    return Course(code=org_unit["Code"], section="", term="", title=org_unit["Name"], source=NAME)


def _get_json(req, base: str, path: str):
    r = req.get(f"{base}{path}")
    if r.status == 401:
        raise session.NotLoggedIn(path)
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return json.loads(r.text())


# A page cap, not a real ceiling on how many enrollments a student can have -
# "a server that repeats a Bookmark must not hang us" (BRIEF minor finding),
# same idea as lauds.session.get_all's own max_pages.
MAX_PAGES = 1000


def _enrollments(req, base: str) -> list[dict]:
    """All of the student's active enrollments, following D2L's own bookmark
    pagination (`PagingInfo.Bookmark`/`HasMoreItems`, the standard, documented
    paging fields for this API)."""
    path = MYENROLLMENTS
    items: list[dict] = []
    for _ in range(MAX_PAGES):
        page = _get_json(req, base, path)
        items += page.get("Items", [])
        paging = page.get("PagingInfo", {})
        if not paging.get("HasMoreItems") or not paging.get("Bookmark"):
            return items
        path = f"{MYENROLLMENTS}&bookmark={paging['Bookmark']}"
    raise RuntimeError(f"Brightspace enrollment pagination did not end after {MAX_PAGES} pages")


def _run(req, base: str) -> tuple[list[Course], list]:
    _get_json(req, base, "/d2l/api/lp/unstable/users/whoami")  # confirms the session is live
    return [to_course(e) for e in _enrollments(req, base)], []


def fetch(base: str) -> Bundle:
    """Return a Bundle of the student's active Brightspace course
    enrollments. `items` is always `[]` today - see the module docstring's
    "Items" section. `base` may be a bare origin or a full course URL,
    normalised to the origin once here so login and every API call agree.
    Opens a browser window to log in if there's no saved session."""
    origin = _origin(base)
    courses, items = session.fetch_with_session(NAME, origin, lambda req: _run(req, origin))
    return Bundle(courses=courses, items=items)
