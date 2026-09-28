"""Blackboard Learn (Ultra) adapter: browser-session login (lauds.session),
then Blackboard's own public REST API (`/learn/api/public/v1/...`) for
courses. Clean port of main's hub/blackboard.py.

**[unverified] EVERYTHING IN THIS MODULE IS AN INFORMED HYPOTHESIS, NOT A
CONFIRMED FACT** (carried over verbatim from main - nothing changed that
status). UBC does not run Blackboard, so there is no Blackboard tenant
anywhere on this project to test any of this against. The hypothesis (see
main's module docstring for the full argument, not repeated here): a logged-in
Ultra session cookie reaches the same documented `/learn/api/public/v1/...`
endpoints the Ultra web UI itself calls - the same pattern hub/brightspace.py
(this project's own `lauds/adapters/brightspace.py`) verified live for
Brightspace's Ultra-equivalent UI, but never itself confirmed for Blackboard.

Documented (developer.blackboard.com) endpoints this hypothesis rests on:
- `GET /learn/api/public/v1/users/me` - the documented `me` alias for the
  calling user; used only to confirm the session is live and read `id`.
- `GET /learn/api/public/v1/users/{userId}/courses` - one membership per
  enrolled course, `{"results": [...], "paging": {"nextPage": "..."}}`.
- `GET /learn/api/public/v1/courses/{courseId}?expand=term` - `courseId` is
  the human-readable code, `name` the title, `?expand=term` documented to
  embed the Term resource inline; tolerated as absent (`term` left blank).

**Items (due dates): not built here, on purpose** - the same honest gap
hub/brightspace.py documents. Blackboard's docs describe calendar *objects*
(id/name/type), never a documented feed of dated due items, so `fetch()`
returns real (hypothesised-real) courses and an empty item list rather than
scrape Ultra's rendered HTML.

Blackboard is multi-tenant (every institution runs its own subdomain) - `base`
is always an explicit argument, never a module constant.

Try it (will fail without a real Blackboard instance and login):
  uv run python -m lauds.cli sync blackboard
"""
import json

from lauds import session
from lauds.models import Bundle, Course

NAME = "blackboard"
DESCRIPTION = "Blackboard Learn: course memberships [unverified, no live tenant] (no due-date feed)"


def login(base: str) -> None:
    """Open a visible browser at `base`; the student signs in through
    whatever SSO that institution fronts Blackboard with.
    [unverified]: never tried against a real Blackboard login page."""
    session.login(NAME, base)


def _get_json(req, base: str, path: str):
    # `path` is normally relative ("/learn/api/public/v1/..."), but next_page()
    # forwards whatever a tenant's own `paging.nextPage` field contains - if
    # some tenant version ever hands back a full absolute URL there instead,
    # don't silently glue it onto `base` and build a broken, doubled-up URL.
    if path.startswith(("http://", "https://")):
        # BRIEF minor finding: an absolute nextPage must still be refused
        # off `base`'s own origin - a misbehaving (or compromised) tenant
        # response must never redirect the saved session's requests to an
        # attacker-controlled host.
        if not path.startswith(base.rstrip("/") + "/") and path.rstrip("/") != base.rstrip("/"):
            raise RuntimeError(f"Blackboard nextPage left the course's own origin: {path!r}")
        url = path
    else:
        url = f"{base}{path}"
    r = req.get(url)
    if r.status == 401:
        raise session.NotLoggedIn(path)
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return json.loads(r.text())


def next_page(page: dict) -> str | None:
    """Blackboard's documented list-response shape is
    `{"results": [...], "paging": {"nextPage": "/learn/api/public/v1/...&offset=N"}}`.
    Returns that relative path, or None once there isn't one.
    [unverified] end-to-end since it's never seen a real Blackboard response,
    but this exact shape is what Blackboard's own REST API docs describe for
    every list resource."""
    return (page.get("paging") or {}).get("nextPage")


# A page cap, not a real ceiling on how many courses a student can have -
# "a server that repeats a Bookmark/nextPage must not hang us" (BRIEF minor
# finding), same idea as lauds.session.get_all's own max_pages.
MAX_PAGES = 1000


def _get_all(req, base: str, path: str) -> list[dict]:
    out: list[dict] = []
    for _ in range(MAX_PAGES):
        page = _get_json(req, base, path)
        out += page.get("results", [])
        path = next_page(page)
        if not path:
            return out
    raise RuntimeError(f"Blackboard pagination did not end after {MAX_PAGES} pages")


def to_course(course: dict) -> Course:
    """One Blackboard Courses resource object -> a Course. `courseId` is the
    *human-readable* code (Blackboard's docs distinguish it from the internal
    `id` primary key used in URLs), `name` is the title. `?expand=term` is
    documented to nest a Term resource under `term`; if a tenant doesn't
    honour that, `term` is left blank rather than guessed. There is no
    documented per-student "section" distinct from the course itself, so
    `section` is always left blank too."""
    return Course(
        code=course.get("courseId") or course.get("id", ""),
        section="",
        term=(course.get("term") or {}).get("name", ""),
        title=course.get("name", ""),
        source=NAME,
    )


def _courses(req, base: str, user_id) -> list[Course]:
    memberships = _get_all(req, base, f"/learn/api/public/v1/users/{user_id}/courses")
    courses = []
    for m in memberships:
        course_id = m.get("courseId")
        if not course_id:
            continue  # malformed membership row; skip rather than guess an id
        courses.append(to_course(_get_json(req, base, f"/learn/api/public/v1/courses/{course_id}?expand=term")))
    return courses


def _run(req, base: str) -> tuple[list[Course], list]:
    # [unverified] `me` alias - see module docstring. Also doubles as the
    # "confirm the session is actually live" check.
    me = _get_json(req, base, "/learn/api/public/v1/users/me")
    return _courses(req, base, me["id"]), []


def fetch(base: str) -> Bundle:
    """Return a Bundle of the student's Blackboard course memberships.
    `items` is always `[]` today - see the module docstring's "Items"
    section. Opens a browser window to log in if there's no saved session.

    [unverified] end to end: no real Blackboard instance has ever answered
    these requests."""
    courses, items = session.fetch_with_session(NAME, base, lambda req: _run(req, base))
    return Bundle(courses=courses, items=items)


def parse_capture(capture: dict) -> tuple[list[Course], list]:
    """Map the experimental extension's captured Blackboard course JSON
    through this adapter's own mapper."""
    if not isinstance(capture, dict) or capture.get("source") != NAME:
        raise ValueError("expected Blackboard capture")
    raw_courses = capture.get("courses")
    if (not isinstance(raw_courses, list) or len(raw_courses) > 100
            or any(not isinstance(row, dict) for row in raw_courses)):
        raise ValueError("invalid Blackboard capture")
    return [to_course(course) for course in raw_courses], []
