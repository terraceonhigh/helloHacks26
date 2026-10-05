"""Canvas adapter for local browser sessions or hosted OAuth access tokens.

The student logs in to canvas.ubc.ca themselves (CWL + Duo) in a real browser
window (hub.site handles that part). We reuse that session to call the same
/api/v1 JSON endpoints Canvas's own web pages use. We never see or store the
CWL password.

Try it:  uv run python -m hub.canvas
"""
import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests

from hub import site
from hub.models import Course, Item, category_for

BASE = "https://canvas.ubc.ca"
SITE = "canvas"
# Canvas's plannable_type -> our kind. Unlisted types (assignment, discussion_topic,
# wiki_page, ...) default to "assignment": still a task, just not one we've named yet.
KINDS = {"announcement": "announcement", "calendar_event": "event", "quiz": "quiz"}


def unwrap(text):
    # Canvas prefixes cookie-authenticated JSON with while(1); to block JSON hijacking.
    return json.loads(text.removeprefix("while(1);"))


def to_course(c):
    enr = next(iter(c.get("enrollments") or []), {})
    return Course(
        code=c.get("course_code", ""),
        section="",  # ponytail: Canvas codes aren't consistent enough to split; match on Workday's side
        term=(c.get("term") or {}).get("name", ""),
        title=c.get("name", ""),
        grade=enr.get("computed_current_score"),
    )


def done_from_submissions(p):
    # Verified against a real planner/items response: "submissions" is a dict
    # (submitted/excused/graded/...) for anything gradeable, or a bare `false`
    # for announcements/events - nothing to report there, so None not False.
    #
    # `planner_override.marked_complete` is Canvas's own to-do-list checkbox:
    # a student can tick an item off without submitting anything at all (a
    # reading, a task with no submission), and that's the signal Canvas's
    # own Planner/Dashboard uses to cross an item out. Checked alongside
    # submissions so a manually-completed item doesn't keep showing as due
    # just because nothing was ever "submitted". Live-verified end to end on
    # the self-hosted Canvas (PM review, #15/#71): marking/unmarking/deleting
    # the override round-trips correctly through this function.
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
    # announcement's plannable_date sat well in the past. Treating that as a
    # `due` made every announcement look permanently overdue. Announcements
    # aren't due anything, so they get no due date at all (excluded from
    # hub.db.upcoming(), which requires one - they're not a task to do).
    due = p.get("plannable_date") if kind != "announcement" else None
    return Item(
        course=course_codes.get(p.get("course_id"), p.get("context_name", "")),
        category=category_for(kind),
        kind=kind,
        title=(p.get("plannable") or {}).get("title", ""),
        due=datetime.fromisoformat(due) if due else None,
        # planner/items' html_url is relative for assignments but already-absolute
        # for calendar events - urljoin leaves an absolute one alone instead of
        # double-prefixing it with BASE (was breaking every event deep link).
        url=urljoin(BASE, p.get("html_url", "")),
        source="canvas",
        done=done_from_submissions(p),
    )


def to_undated_item(a, course_code):
    """/courses/:id/assignments row with no due date - planner/items never
    returns these at all (#15), so a no-due-date assignment used to just
    vanish. due=None either way; hub.db still shows it, just unsorted."""
    return Item(
        course=course_code, category=category_for("assignment"), kind="assignment",
        title=a.get("name", ""), due=None, url=urljoin(BASE, a.get("html_url", "")),
        source="canvas", done=a.get("has_submitted_submissions"),
    )


def login():
    """Open a visible browser; the student signs in; we save the session."""
    site.login(SITE, BASE)


def authorization_url(client_id, redirect_uri, state):
    """URL for Canvas's server-side authorization-code flow.

    The HTTP layer creates and verifies a one-time state value. Never place
    the client secret, a token, or a student's password in this URL.
    """
    if not all((client_id, redirect_uri, state)):
        raise ValueError("Canvas OAuth configuration or state is missing")
    return f"{BASE}/login/oauth2/auth?{urlencode({
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'state': state,
    })}"


def _token_request(client_id, client_secret, grant_type, **fields):
    if not client_id or not client_secret or not all(fields.values()):
        raise ValueError("Canvas OAuth credentials or grant value is missing")
    response = requests.post(
        f"{BASE}/login/oauth2/token",
        data={"grant_type": grant_type, "client_id": client_id,
              "client_secret": client_secret, **fields},
        timeout=15,
        allow_redirects=False,
    )
    # Never include Canvas's response body here: an upstream error may echo a
    # code, token, or client secret and end up in public server logs.
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Canvas OAuth token request failed ({response.status_code})")
    try:
        tokens = response.json()
    except ValueError:
        raise RuntimeError("Canvas OAuth token response is invalid JSON") from None
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise RuntimeError("Canvas OAuth token response is incomplete")
    return tokens


def exchange_code(client_id, client_secret, redirect_uri, code):
    """Exchange a one-use callback code for Canvas access/refresh tokens."""
    return _token_request(client_id, client_secret, "authorization_code",
                          redirect_uri=redirect_uri, code=code)


def refresh_token(client_id, client_secret, token):
    """Refresh access; Canvas keeps the same refresh token across refreshes."""
    return _token_request(client_id, client_secret, "refresh_token",
                          refresh_token=token)


class _BearerResponse:
    """Expose requests' response through the small interface site.get_all uses."""

    def __init__(self, response):
        self.status = response.status_code
        self.ok = 200 <= self.status < 300
        self.headers = response.headers
        self._response = response

    def text(self):
        return self._response.text


class _BearerRequest:
    def __init__(self, session):
        self.session = session

    def get(self, url):
        parsed = urlparse(url)
        # Canvas supplies pagination links. Never forward a student's bearer
        # token to a different origin, even if an upstream Link header says to.
        if (parsed.scheme != "https" or parsed.hostname != urlparse(BASE).hostname
                or parsed.port is not None or parsed.username or parsed.password
                or not parsed.path.startswith("/api/v1/")):
            raise ValueError("Canvas API pagination left the allowed origin")
        return _BearerResponse(self.session.get(url, timeout=15, allow_redirects=False))


def fetch(start=None, end=None, *, access_token=None):
    """Return (courses, items) for start..end, using OAuth or local login.

    Default is a whole UBC term either side of today (~4 months), not just
    the coming week: planner/items needs *some* range, and Canvas doesn't
    hand back "the whole term" for us to use instead.
    """
    start = start or date.today() - timedelta(days=120)
    end = end or date.today() + timedelta(days=120)
    if access_token is None:
        return site.fetch_with_session(SITE, BASE, lambda req: _run(req, start, end))
    if not access_token:
        raise ValueError("Canvas access token is empty")
    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bearer {access_token}"})
        return _run(_BearerRequest(session), start, end)


def _run(req, start, end):
    raw = site.get_all(req, f"{BASE}/api/v1/courses", {
        "include[]": ["total_scores", "term"], "enrollment_state": "active", "per_page": 100}, unwrap)
    courses = [to_course(c) for c in raw]
    codes = {c["id"]: c.get("course_code", "") for c in raw}
    plan = site.get_all(req, f"{BASE}/api/v1/planner/items", {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "per_page": 100}, unwrap)
    items = [to_item(p, codes) for p in plan]
    # ponytail: one extra call per course to catch undated assignments
    # planner/items drops entirely - fine at hackathon scale, batch/parallelize
    # if course counts ever make this slow.
    for c in raw:
        assignments = site.get_all(req, f"{BASE}/api/v1/courses/{c['id']}/assignments", {"per_page": 100}, unwrap)
        items += [to_undated_item(a, codes.get(c["id"], "")) for a in assignments if not a.get("due_at")]
    return courses, items


def parse_capture(capture):
    """Map a minimal browser-extension capture through this Canvas adapter.

    The extension transports JSON from the student's own signed-in tab. This
    remains the only place that turns Canvas records into our shared model.
    """
    if not isinstance(capture, dict) or capture.get("source") != SITE:
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
    return courses, items


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    db.save(db.connect(), courses, items)  # persist so hub.db.upcoming() etc. can query it later
    for c in courses:
        print(f"{c.code:30} {c.grade if c.grade is not None else '-':>6}  {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or 0)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:20} {i.title}")
