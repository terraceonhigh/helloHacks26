"""Google Classroom adapter: real OAuth2 user consent, not a browser-cookie
session.

Every other logged-in adapter in `hub/` (Canvas, PrairieLearn) reuses
`hub.site`'s pattern: open a real browser, the student signs in, save the
session cookies. Classroom's REST API doesn't work that way at all - it's a
Bearer-token API, and getting a token needs Google's own "installed app" /
loopback-IP-redirect OAuth2 authorization-code flow (the flow Google
documents for a desktop/CLI app, not a website). So this file is its own
small OAuth2 client instead of going through `hub.site`.

The student supplies their OWN OAuth client id/secret - a "Desktop app" OAuth
client they create themselves in Google Cloud Console - never a shared
project key. Same "bring your own credentials" principle this repo already
uses for Canvas PATs (see `hub/canvas.py`) and the student's own API key in
`hub/syllabus.py`. Nothing here embeds or hardcodes a credential.

Two calls: `authorize(client_id, client_secret)` runs the one-time consent
flow and saves a token (mirroring `hub.site.login`'s naming and its
`~/.ubc-hub/`, mode-0600, never-in-the-repo convention - see AGENTS.md rule
3 - even though the mechanism is OAuth2, not a saved cookie jar). `fetch()`
loads that token (refreshing it first if it's expired) and calls the real
REST API with `requests` - no new dependency; a plain `requests.post` to
Google's token endpoint is a complete enough OAuth2 client for this, so
`google-auth-oauthlib` / `google-api-python-client` aren't needed.

Try it (after `authorize(...)` has been run once):  uv run python -m hub.google_classroom

## What's a cited, current, real API fact vs a genuine unknown

Fetched directly from developers.google.com on 2026-09-26 (this session -
not from training-data memory, per this adapter's instructions):

- Authorization endpoint `https://accounts.google.com/o/oauth2/v2/auth` and
  token endpoint `https://oauth2.googleapis.com/token`, and the loopback
  redirect (`http://127.0.0.1:PORT`) + authorization-code exchange
  (`code`, `client_id`, `client_secret`, `redirect_uri`, `code`,
  `grant_type=authorization_code`) and refresh
  (`grant_type=refresh_token`, `refresh_token`, `client_id`) shapes:
  https://developers.google.com/identity/protocols/oauth2/native-app
- Scope strings `https://www.googleapis.com/auth/classroom.courses.readonly`
  and `.../classroom.coursework.me.readonly`:
  docs/api-standards.md's existing citation of
  https://developers.google.com/workspace/classroom/guides/auth
- `courses.list` -> `GET /v1/courses`, Course fields incl. `id`, `name`,
  `section`, `courseState`, `alternateLink`:
  https://developers.google.com/workspace/classroom/reference/rest/v1/courses
- `courses.courseWork.list` -> `GET /v1/courses/{courseId}/courseWork`,
  CourseWork fields incl. `id`, `title`, `state`, `alternateLink`, `dueDate`,
  `dueTime`, `workType`:
  https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork
- `dueDate` is a `google.type.Date` (`year`, `month`, `day`); `dueTime` is a
  `google.type.TimeOfDay` (`hours`, `minutes`, `seconds`, `nanos`); Classroom's
  own docs describe `dueTime` as "in UTC" - so `_due()` below always builds a
  UTC datetime, never a naive one or a guess at the course's own timezone:
  same CourseWork reference page as above.
- `courses.courseWork.studentSubmissions.list` ->
  `GET /v1/courses/{courseId}/courseWork/{courseWorkId}/studentSubmissions`,
  where `courseWorkId="-"` fetches every submission across a whole course in
  one call and `userId="me"` means the caller's own submissions, paginated
  with `pageToken`/`nextPageToken`:
  https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions/list
- `SubmissionState` enum values `CREATED`, `TURNED_IN`, `RETURNED`,
  `RECLAIMED_BY_STUDENT`, `STUDENT_EDITED_AFTER_TURN_IN` (plus
  `STATE_UNSPECIFIED`):
  https://developers.google.com/workspace/classroom/reference/rest/v1/courses.courseWork.studentSubmissions#SubmissionState

Genuine unknowns / not independently confirmed this session (flagged
in-line as `[unverified]` at point of use too):
- The exact `CourseWorkType` enum member spellings (`ASSIGNMENT`,
  `SHORT_ANSWER_QUESTION`, `MULTIPLE_CHOICE_QUESTION`,
  `COURSE_WORK_TYPE_UNSPECIFIED`) - the reference page confirms the field
  exists and is immutable but the fetch tool didn't return its enum list, so
  these spellings come from training-data memory, not a citation.
- Whether `courses.list` / `courses.courseWork.list` use the exact same
  `pageToken`/`nextPageToken` pagination shape as `studentSubmissions.list`
  (documented above) - very likely, since it's Google's standard list-method
  convention across every Google API, but not fetched page-by-page here.
- Whether `STUDENT_EDITED_AFTER_TURN_IN` should read as "done" - genuinely
  ambiguous (it means the student touched their submission again after
  turning it in, possibly after the teacher already returned it), so it's
  mapped to `None` (unknown) rather than guessed either way.
- No live Google account or OAuth client was available in this sandbox, so
  `authorize()` and the live network path of `fetch()` are untested against
  a real Google response - only the pure parsing/mapping functions are
  covered by `tests/test_google_classroom.py`, against fixtures built
  directly from the field shapes cited above.
"""
import http.server
import json
import secrets
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from hub.models import Course, Item, category_for

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
API_BASE = "https://classroom.googleapis.com/v1"
SOURCE = "google_classroom"

# Real, current scope strings - see module docstring's citations.
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
]

# CourseWorkType -> our kind. [unverified] exact enum spellings - see
# module docstring. Unlisted/unknown types fall back to "assignment", same
# safe default hub/canvas.py uses for its own unlisted plannable_types.
KINDS = {
    "SHORT_ANSWER_QUESTION": "assignment",
    "ASSIGNMENT": "assignment",
    "MULTIPLE_CHOICE_QUESTION": "quiz",
}

# SubmissionState -> done. Cited enum values, see module docstring.
# STUDENT_EDITED_AFTER_TURN_IN, STATE_UNSPECIFIED and anything else missing
# here fall through to None (unknown), not a guess.
DONE_FROM_STATE = {
    "TURNED_IN": True,
    "RETURNED": True,
    "CREATED": False,
    "RECLAIMED_BY_STUDENT": False,
}


def token_path():
    # Same directory and naming convention as hub.site.state_path, even
    # though this stores an OAuth2 token, not a Playwright cookie jar.
    return Path.home() / ".ubc-hub" / "google_classroom-token.json"


def _save_token(token):
    path = token_path()
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(json.dumps(token))
    path.chmod(0o600)  # never world/group readable - it's a live credential


def _load_token():
    path = token_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


class _RedirectCatcher(http.server.BaseHTTPRequestHandler):
    """Catches exactly one redirect from Google's consent screen on
    http://127.0.0.1:<port> (the loopback flow's own required shape - see
    module docstring). Stdlib http.server only, matching hub/api.py's
    existing "no new dependency for a tiny local server" precedent."""

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        self.server.auth_code = query.get("code", [None])[0]
        self.server.auth_state = query.get("state", [None])[0]
        self.server.auth_error = query.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>UBC Hub: Google sign-in complete. You can close this tab.</body></html>")

    def log_message(self, fmt, *args):
        pass  # quiet by default, matches hub/api.py's Handler


def authorize(client_id, client_secret, base=AUTH_ENDPOINT, timeout=300):
    """One-time OAuth2 consent: open the system browser to Google's consent
    screen, catch the redirect on a short-lived local server, exchange the
    code for tokens, and save them for `fetch()` to reuse (refreshing
    instead of re-consenting every run). Raises on failure rather than
    silently leaving a bad/missing token - the caller decides how to surface
    that to the student; `fetch()` is what stays quiet-and-return-[] on
    failure, matching every other adapter."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _RedirectCatcher)
    server.auth_code = server.auth_state = server.auth_error = None
    server.timeout = timeout
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    try:
        url = f"{base}?{urlencode({
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(SCOPES),
            'access_type': 'offline',  # asks for a refresh_token, not just a short-lived access token
            'prompt': 'consent',
            'state': state,
        })}"
        webbrowser.open(url)
        server.handle_request()  # blocks for exactly one request (or times out)
    finally:
        server.server_close()

    if server.auth_error:
        raise RuntimeError(f"Google sign-in was refused: {server.auth_error}")
    if not server.auth_code or server.auth_state != state:
        raise RuntimeError("Google sign-in did not complete (no code, or a state mismatch)")

    resp = requests.post(TOKEN_ENDPOINT, data={
        "code": server.auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=15)
    resp.raise_for_status()
    token = resp.json()
    token["client_id"], token["client_secret"] = client_id, client_secret
    token["obtained_at"] = time.time()
    _save_token(token)


def _refresh(token):
    resp = requests.post(TOKEN_ENDPOINT, data={
        "refresh_token": token["refresh_token"],
        "client_id": token["client_id"],
        "client_secret": token["client_secret"],
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    fresh = resp.json()
    token = {**token, **fresh, "obtained_at": time.time()}
    _save_token(token)
    return token


def _access_token(token):
    """Refresh a minute early rather than right at expiry, so a slow request
    doesn't land on an already-dead token."""
    expires_in = token.get("expires_in", 3600)
    if time.time() >= token.get("obtained_at", 0) + expires_in - 60:
        token = _refresh(token)
    return token["access_token"], token


def to_course(c):
    # Classroom's Course resource has no term/semester field at all (see
    # module docstring's citation) - left blank like hub/canvas.py leaves
    # `section` blank, so hub.db's canonical-code join still matches it up
    # against Canvas/Workday rows for the same real course.
    name = c.get("name", "")
    return Course(code=name, section=c.get("section", ""), term="", title=name, grade=None)


def _due(work):
    """CourseWork's dueDate (google.type.Date: year/month/day) + dueTime
    (google.type.TimeOfDay: hours/minutes/seconds/nanos) -> one tz-aware
    UTC datetime - Classroom's own docs say dueTime is in UTC (see module
    docstring), so this never guesses at the course's own timezone. No
    dueDate at all -> None, same as Canvas's own "not every kind has a due
    date" pattern in hub/canvas.py."""
    d = work.get("dueDate")
    if not d:
        return None
    t = work.get("dueTime") or {}
    return datetime(
        d["year"], d["month"], d["day"],
        t.get("hours", 0), t.get("minutes", 0), t.get("seconds", 0),
        tzinfo=timezone.utc,
    )


def _url(work):
    # alternateLink is real and documented, but only guaranteed once
    # coursework is published - a DRAFT item may have none. hub/webwork.py's
    # first draft once let two Items both get url="" and collide on hub.db's
    # UNIQUE(source, url); courseId+id is always present and always unique
    # per Classroom course, so it's a safe fallback rather than risking that
    # same bug here.
    return work.get("alternateLink") or f"https://classroom.google.com/c/{work.get('courseId', '')}/a/{work.get('id', '')}"


def to_item(work, course_code, done_map):
    kind = KINDS.get(work.get("workType"), "assignment")
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=work.get("title", ""),
        due=_due(work),
        url=_url(work),
        source=SOURCE,
        done=done_map.get(work.get("id")),
    )


def _done_from_state(state):
    return DONE_FROM_STATE.get(state)  # anything else (incl. None) -> None: unknown, not a guess


def done_map_from_submissions(submissions):
    """One done-state per courseWorkId. A student has at most one submission
    per piece of coursework, so the last one seen for a given id wins - in
    practice there's only ever one."""
    return {s["courseWorkId"]: _done_from_state(s.get("state"))
            for s in submissions if s.get("courseWorkId")}


def _get_all(session, url, params, key):
    """GET, following Classroom's own pageToken/nextPageToken pagination -
    confirmed on courses.courseWork.studentSubmissions.list (see module
    docstring); courses.list/courses.courseWork.list are assumed to share it
    since it's Google's standard list-method shape, [unverified] specifically
    for those two calls."""
    out, page_token = [], None
    while True:
        params_now = dict(params, pageToken=page_token) if page_token else params
        r = session.get(url, params=params_now, timeout=15)
        r.raise_for_status()
        data = r.json()
        out += data.get(key, [])
        page_token = data.get("nextPageToken")
        if not page_token:
            return out


def fetch():
    """Return (courses, items). No saved token -> nothing to do, same
    "unavailable, don't crash" contract as every other adapter (AGENTS.md).
    Any auth/network/parse failure along the way returns ([], []) too."""
    token = _load_token()
    if token is None:
        return [], []
    try:
        access_token, token = _access_token(token)
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {access_token}"

        raw_courses = _get_all(session, f"{API_BASE}/courses", {"courseStates": "ACTIVE"}, "courses")
        courses = [to_course(c) for c in raw_courses]
        codes = {c["id"]: c.get("name", "") for c in raw_courses}

        items = []
        for c in raw_courses:
            course_id = c["id"]
            try:
                work = _get_all(session, f"{API_BASE}/courses/{course_id}/courseWork", {}, "courseWork")
                subs = _get_all(session, f"{API_BASE}/courses/{course_id}/courseWork/-/studentSubmissions",
                                 {"userId": "me"}, "studentSubmissions")
            except Exception:
                continue  # this course's coursework/submissions call failed; keep the other courses' items
            done_map = done_map_from_submissions(subs)
            for w in work:
                try:
                    items.append(to_item(w, codes.get(course_id, ""), done_map))
                except Exception:
                    # One malformed courseWork item (e.g. a dueDate missing a
                    # field) must not discard every other course's already-
                    # parsed items along with it - the old list-comprehension
                    # version let one bad item's exception propagate out of
                    # this whole function via the outer except below.
                    continue
        return courses, items
    except Exception:
        # ponytail: one broad catch at the adapter boundary - a dead token,
        # a network blip or an unexpected response shape shouldn't take the
        # dashboard down with it. Matches hub/api.py's own comment on this
        # same tradeoff.
        return [], []


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    if not courses and not items:
        print("No saved token, or fetch failed. Run authorize(client_id, client_secret) first.")
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:30} {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or 0)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:20} {i.title}")
