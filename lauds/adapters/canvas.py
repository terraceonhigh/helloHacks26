"""Canvas adapter: a local browser session (default) or a personal access
token (`lauds config set canvas.access_token <token>`, then `lauds sync
canvas` - no `login` step at all for the token path; BRIEF finding: this
docstring used to claim a `lauds login canvas --token` flag that never
existed and left `access_token` unreachable from the CLI. `login()` itself
never takes a token - it always opens the real browser session - so the
token path is config-only). Clean port of main's hub/canvas.py.

Not ported, on purpose: the server-side OAuth authorization-code exchange
(`authorization_url`/`exchange_code`/`refresh_token`, `_BearerRequest`'s
callback-flow half). That flow existed only for the hosted Vercel product's
`/api/canvas/callback` (hub/api.py, thrown out per BRIEF.md) - it needs a
`redirect_uri` and a `client_secret` a CLI has no way to receive safely.
A CLI reads a personal access token straight from the student (Canvas
Settings > New Access Token) and calls the API directly instead; that half
of hub/canvas.py's Bearer path - and its "never forward the token off
Canvas's own origin, even to a paginated Link header" guard - is kept below
as `_TokenRequest`.

Try it:  uv run python -m lauds.cli sync canvas
"""
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse

from lauds import session
from lauds.models import Bundle, Course, Item, category_for

NAME = "canvas"
DESCRIPTION = "UBC Canvas: assignments, quizzes, events, announcements"
BASE = "https://canvas.ubc.ca"

# Canvas's plannable_type -> our kind. Unlisted types (assignment, discussion_topic,
# wiki_page, ...) default to "assignment": still a task, just not one we've named yet.
KINDS = {"announcement": "announcement", "calendar_event": "event", "quiz": "quiz"}


def unwrap(text):
    # Canvas prefixes cookie-authenticated JSON with while(1); to block JSON hijacking.
    # A bearer-token call gets plain JSON back - removeprefix is a no-op then.
    return json.loads(text.removeprefix("while(1);"))


def to_course(c):
    enr = next(iter(c.get("enrollments") or []), {})
    return Course(
        code=c.get("course_code", ""),
        section="",  # ponytail: Canvas codes aren't consistent enough to split; match on Workday's side
        term=(c.get("term") or {}).get("name", ""),
        title=c.get("name", ""),
        grade=enr.get("computed_current_score"),
        source=NAME,
    )


def done_from_submissions(p):
    # Verified against a real planner/items response: "submissions" is a dict
    # (submitted/excused/graded/...) for anything gradeable, or a bare `false`
    # for announcements/events - nothing to report there, so None not False.
    #
    # `planner_override.marked_complete` is Canvas's own to-do-list checkbox:
    # a student can tick an item off without submitting anything at all (a
    # reading, a task with no submission), and that's the signal Canvas's
    # own Planner/Dashboard uses to cross an item out.
    submissions = p.get("submissions")
    override = p.get("planner_override")
    marked_complete = bool(override.get("marked_complete")) if isinstance(override, dict) else False
    if not isinstance(submissions, dict) and not marked_complete:
        return None
    submitted_or_excused = isinstance(submissions, dict) and bool(submissions.get("submitted") or submissions.get("excused"))
    return submitted_or_excused or marked_complete


def to_item(p, course_codes):
    kind = KINDS.get(p.get("plannable_type"), "assignment")
    # Canvas's planner `plannable_date` is a real deadline for assignments/
    # quizzes/events, but for an announcement it's just when it was posted -
    # verified against a real planner/items response, where every
    # announcement's plannable_date sat well in the past. An announcement
    # gets no due date at all: it isn't a task to do.
    due = p.get("plannable_date") if kind != "announcement" else None
    plannable = p.get("plannable") or {}
    return Item(
        course=course_codes.get(p.get("course_id"), p.get("context_name", "")),
        category=category_for(kind),
        kind=kind,
        title=plannable.get("title", ""),
        due=datetime.fromisoformat(due) if due else None,
        # planner/items' html_url is relative for assignments but already-absolute
        # for calendar events - urljoin leaves an absolute one alone instead of
        # double-prefixing it with BASE.
        url=urljoin(BASE, p.get("html_url", "")),
        source=NAME,
        done=done_from_submissions(p),
        description=plannable.get("description") or None,
        points=plannable.get("points_possible"),
    )


def to_undated_item(a, course_code):
    """/courses/:id/assignments row with no due date - planner/items never
    returns these at all, so a no-due-date assignment used to just vanish.
    due=None either way; lauds still shows it, just unsorted."""
    return Item(
        course=course_code, category=category_for("assignment"), kind="assignment",
        title=a.get("name", ""), due=None, url=urljoin(BASE, a.get("html_url", "")),
        source=NAME, done=a.get("has_submitted_submissions"),
        description=a.get("description") or None, points=a.get("points_possible"),
    )


def login(**opts):
    """Open a visible browser; the student signs in; we save the session."""
    session.login(NAME, BASE)


class _TokenResponse:
    """Expose requests' response through the small shape lauds.session's
    pagination helpers use."""

    def __init__(self, response):
        self.status = response.status_code
        self.ok = 200 <= self.status < 300
        self.headers = response.headers
        self._response = response

    def text(self):
        return self._response.text


class _TokenRequest:
    """A personal-access-token session, in the same `req.get(url)` shape
    lauds.session's pagination helpers expect (they reuse it for 429 backoff
    and Link-header pagination unchanged; only the transport differs from
    the browser-session path). Every call - not just a followed pagination
    link - is refused off Canvas's own /api/v1 origin and never follows a
    redirect: a self-hosted token must never leak to an attacker-controlled
    host, even one a compromised or misconfigured server redirects to."""

    def __init__(self, token):
        if not token:
            raise ValueError("Canvas access token is empty")
        import requests
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, url):
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != urlparse(BASE).hostname
                or parsed.port is not None or parsed.username or parsed.password
                or not parsed.path.startswith("/api/v1/")):
            raise ValueError("Canvas API pagination left the allowed origin")
        return _TokenResponse(self._session.get(url, timeout=15, allow_redirects=False))


def fetch(start=None, end=None, *, access_token=None):
    """Return a Bundle of courses + items for start..end.

    Default is a whole UBC term either side of today (~4 months), not just
    the coming week: planner/items needs *some* range, and Canvas doesn't
    hand back "the whole term" for us to use instead.
    """
    start = start or date.today() - timedelta(days=120)
    end = end or date.today() + timedelta(days=120)
    if access_token is not None:
        return _run(_TokenRequest(access_token), start, end)
    return session.fetch_with_session(NAME, BASE, lambda req: _run(req, start, end))


def _run(req, start, end):
    raw = session.get_all(req, f"{BASE}/api/v1/courses", {
        "include[]": ["total_scores", "term"], "enrollment_state": "active", "per_page": 100}, unwrap)
    courses = [to_course(c) for c in raw]
    codes = {c["id"]: c.get("course_code", "") for c in raw}
    plan = session.get_all(req, f"{BASE}/api/v1/planner/items", {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "per_page": 100}, unwrap)
    items = [to_item(p, codes) for p in plan]
    # ponytail: one extra call per course to catch undated assignments
    # planner/items drops entirely - fine at this scale, batch/parallelize
    # if course counts ever make this slow.
    for c in raw:
        assignments = session.get_all(req, f"{BASE}/api/v1/courses/{c['id']}/assignments", {"per_page": 100}, unwrap)
        items += [to_undated_item(a, codes.get(c["id"], "")) for a in assignments if not a.get("due_at")]
    return Bundle(courses=courses, items=items)


def parse_capture(capture):
    """Map a minimal browser-extension capture through this Canvas adapter.

    The extension transports JSON from the student's own signed-in tab. This
    remains the only place that turns Canvas records into our shared model.
    """
    if not isinstance(capture, dict) or capture.get("source") != NAME:
        raise ValueError("expected a Canvas capture")
    raw_courses = capture.get("courses")
    planner = capture.get("planner")
    undated = capture.get("undated")
    if (not isinstance(raw_courses, list) or not isinstance(planner, list)
            or not isinstance(undated, list) or len(raw_courses) > 100
            or len(planner) > 3000 or len(undated) > 3000):
        raise ValueError("invalid Canvas capture size or shape")
    if any(not isinstance(row, dict) for row in raw_courses + planner + undated):
        raise ValueError("Canvas capture contains a non-object row")
    courses = [to_course(c) for c in raw_courses]
    codes = {c["id"]: c.get("course_code", "") for c in raw_courses}
    items = [to_item(p, codes) for p in planner]
    items += [to_undated_item(a, codes.get(a.get("course_id"), "")) for a in undated]
    for item in items:
        parsed = urlparse(item.url)
        query = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.netloc != urlparse(BASE).netloc
                or parsed.username or parsed.password or parsed.fragment
                or not parsed.path or not item.title
                or set(query) - {"event_id", "include_contexts"}
                or any(not value.isdecimal() for value in query.get("event_id", []))
                or any(not re.fullmatch(r"course_\d+", value) for value in query.get("include_contexts", []))
                or item.due is not None and item.due.tzinfo is None):
            raise ValueError("Canvas capture contains an invalid item")
    return Bundle(courses=courses, items=items)


if __name__ == "__main__":
    bundle = fetch()
    for c in bundle.courses:
        print(f"{c.code:30} {c.grade if c.grade is not None else '-':>6}  {c.title}")
    print()
    for i in sorted(bundle.items, key=lambda i: (i.due is None, i.due)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:20} {i.title}")
