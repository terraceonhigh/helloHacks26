"""Brightspace (D2L) adapter: browser-session login (hub.site), then the
site's own JSON endpoints for course data. Read-only, the student's own
account and own data only, same as every other adapter in this project.

**Verified live** (Terrace, 2026-09-26) against a real UBC course on
`ubc.brightspace.com`. UBC's main LMS is Canvas; this one course happens to
also run through Brightspace, which was enough to check real endpoints:

- `GET /d2l/api/lp/unstable/users/whoami` returns simple JSON identifying
  the logged-in student, using the ordinary browser session (no separate
  developer key needed).
- `GET /d2l/api/lp/1.50/enrollments/myenrollments/?orgUnitTypeId=3&isActive=true&canAccess=true`
  returns the student's own active course enrollments as JSON, same way, with
  a `PagingInfo` cursor (`Bookmark`/`HasMoreItems`) this adapter follows to
  get every enrollment -- the one real account checked has a single active
  course (`HasMoreItems: false`), so the loop itself is untested, but the
  field names are D2L's own documented paging convention, not a guess.

This updates docs/api-standards.md's previous note that Brightspace has no
student self-serve access at all -- that's true of the official developer-key
program, but a normal logged-in browser session reaches this much of the
same data on its own, matching how the Canvas adapter in this project works.

**Items (due dates): not built here, on purpose.** This project's rule for
any site behind a login is: read its JSON, not its rendered page HTML.
Checking Brightspace's own Calendar screens live, they're built from an
older internal format that isn't plain JSON and isn't meant to be read
directly by other programs, and no separate documented JSON endpoint for
calendar/due-date data turned up while testing. So rather than parse that
older format anyway, `fetch()` below returns real courses and an empty item
list, explained here instead of silently skipped. Whether to look further
for a proper due-dates endpoint, or to make a deliberate one-time exception
here, is a call for Jacky/the team, not this file alone.

Brightspace is multi-tenant -- every institution runs its own subdomain or
custom domain, unlike Canvas's single `canvas.ubc.ca` -- so `base` is always
an explicit argument here, never a module-level constant like PrairieLearn's
`BASE`. `base` can be either the bare origin (e.g. "https://ubc.brightspace.com",
matching hub/prairielearn.py's bare-origin convention) or a full course URL
(e.g. "https://ubc.brightspace.com/d2l/home/7067", the more natural thing to
paste when signing in on your own course page -- this is literally how the
live testing above was first done): `fetch()` normalises either to just the
origin before building any API path, so it doesn't matter which is passed.

Try it:  uv run python -m hub.brightspace <base-url>
"""
from urllib.parse import urlsplit

from hub import site
from hub.models import Course

SITE = "brightspace"


def _origin(base):
    """Normalise `base` to just scheme://host, whether it's a bare origin or
    a full course URL -- see the module docstring. Every `/d2l/api/...` path
    below is absolute from the origin, so concatenating a full course URL's
    path in front of it would build a broken, doubled-up URL (confirmed:
    this is exactly what "https://host/d2l/home/<id>" + "/d2l/api/..."
    produces if `base` isn't normalised first)."""
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


def login(base):
    """Open a visible browser at `base`'s origin; the student signs in
    through whatever SSO that institution fronts Brightspace with; save the
    session. Verified for UBC's CWL-fronted flow (this is exactly how the
    real session used to test this module's calls was established, by
    signing in on a specific course's own page -- see the module docstring
    for why a full course URL works fine here too)."""
    site.login(SITE, _origin(base))


def _get_json(req, base, path):
    r = req.get(f"{base}{path}")
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return r.json()


def to_course(enrollment):
    """One entry of `enrollments/myenrollments`'s real `Items` list -> a
    Course. `OrgUnit.Code` is the real, verified `code` shape (e.g.
    "MATH_V 100A ALL SECTIONS 2026W1"); there's no separate section/term
    field in this response, so those are left blank rather than guessed by
    splitting the code text (a future improvement, not a guess to ship)."""
    org_unit = enrollment["OrgUnit"]
    return Course(code=org_unit["Code"], section="", term="", title=org_unit["Name"])


def _enrollments(req, base):
    """All of the student's active enrollments, following D2L's own bookmark
    pagination. The one real account this was checked against has a single
    course (`PagingInfo.HasMoreItems` was `false`), so the loop itself is
    unexercised -- but `PagingInfo.Bookmark`/`HasMoreItems` are D2L's
    standard, documented paging fields, and silently reading only the first
    page for a student with many enrollments would be a real, if untested,
    way to lose courses."""
    path = "/d2l/api/lp/1.50/enrollments/myenrollments/?orgUnitTypeId=3&isActive=true&canAccess=true"
    items = []
    while path:
        page = _get_json(req, base, path)
        items += page.get("Items", [])
        paging = page.get("PagingInfo", {})
        if not paging.get("HasMoreItems") or not paging.get("Bookmark"):
            break
        path = (
            "/d2l/api/lp/1.50/enrollments/myenrollments/"
            f"?orgUnitTypeId=3&isActive=true&canAccess=true&bookmark={paging['Bookmark']}"
        )
    return items


def _run(req, base):
    _get_json(req, base, "/d2l/api/lp/unstable/users/whoami")  # verified reachable; confirms the session is live
    courses = [to_course(e) for e in _enrollments(req, base)]
    return courses, []  # see module docstring: no plain JSON endpoint found for due dates yet


def fetch(base):
    """Return (courses, items) for the student's active Brightspace course
    enrollments. `items` is always `[]` today -- see the module docstring's
    "Items" section for why, and what would need to change that. Opens a
    browser window to log in if there's no saved session. A login failure
    or unexpected response shape returns ([], []) rather than crashing the
    dashboard (AGENTS.md "handle failure without crashing").

    `base` may be a bare origin or a full course URL -- normalised to the
    origin once here, so both the login step and every API call agree."""
    origin = _origin(base)
    try:
        return site.fetch_with_session(SITE, origin, lambda req: _run(req, origin))
    except Exception:
        return [], []


if __name__ == "__main__":
    import sys

    from hub import db

    if len(sys.argv) < 2:
        print("usage: uv run python -m hub.brightspace <base-url>")
        raise SystemExit(1)
    courses, items = fetch(sys.argv[1])
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:30} {c.title}")
    if not items:
        print("\n(no items yet -- see hub/brightspace.py's module docstring)")
