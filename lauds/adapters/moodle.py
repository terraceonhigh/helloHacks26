"""Moodle adapter (other schools; UBC runs Canvas, not Moodle). Clean port of
main's hub/moodle.py, corrected against a real self-hosted Moodle 4.5
(humboldt, `tests/live/moodle_selfhost/README.md`) - the first live ground
truth this adapter has ever had. See that README for the full write-up; the
two real bugs it found in main's own code are fixed here, not reproduced:

1. **`core_enrol_get_users_courses` can never be called through
   `/lib/ajax/service.php` at all** (batched or alone): a stock Moodle 4.5's
   own `lib/db/services.php` has no `'ajax' => true` for that function, so
   the AJAX multiplexer rejects it with `servicenotavailable` before ever
   reaching anything else. main's `_run()` batches it with the calendar call
   in one POST, so the whole batch aborts and the calendar call is never
   even attempted (live-verified: `tests/fixtures/moodle/live_01_post_lib_ajax_service_php.json`).
   Fixed here by never batching (`_ajax_call` sends one call at a time) and
   by never depending on that function succeeding: courses are built from
   each calendar event's own embedded `course` sub-object instead
   (`_courses_from_events`) - real data this adapter already has to fetch
   for items, verified working against the same live server
   (`tests/fixtures/moodle/live_03_post_lib_ajax_service_php.json`). If a
   future Moodle version *does* enable that function, `_run` still tries it
   first and prefers its (richer, but term-less either way) result.
2. **`core_calendar_get_action_events_by_timesort`'s own `limitnum` is
   server-capped at 50**, but main hardcodes 100 - fails even called alone.
   Fixed here (`MAX_LIMITNUM = 50`).

Not fixed, because it isn't a bug - a real gap in what this feed can show
(same README, "Oracle bugs found #3"): the calendar feed never surfaces an
item with no due date or one the student has already submitted/graded.
Nothing in `core_calendar_get_action_events_by_timesort` can change that; a
future adapter wanting those would need `mod_assign_get_assignments` +
`gradereport_user_get_grade_items` (documented, never verified here - same
as main's own noted follow-up).

Why browser-session + AJAX at all, not token.php + password: see main's
module docstring (kept, not repeated) - many institutions front Moodle with
campus SSO, which token.php's own login form doesn't work behind, so the
same "open a real browser, the student logs in themselves" pattern every
other lauds adapter uses is the safer default here too.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urljoin, urlparse

from lauds import session
from lauds.models import Bundle, Course, Item, category_for

NAME = "moodle"
DESCRIPTION = "Moodle: courses + due-date calendar feed (other schools; UBC runs Canvas)"

# Moodle embeds a JS config object on every logged-in page, e.g.
# `M.cfg = {"wwwroot":"https:\/\/moodle.example.edu","sesskey":"AbCd1234",...}`.
# Only this one CSRF-style token is ever pulled back out of it - never parsed
# as HTML, never displayed content, same as a browser reading its own page's
# config object.
SESSKEY_RE = re.compile(r'"sesskey"\s*:\s*"(\w+)"')

# Moodle's modname -> our kind. Unlisted module types default to "assignment"
# - the safest bucket, still a task.
KINDS = {"quiz": "quiz", "assign": "assignment"}

# core_calendar_get_action_events_by_timesort's own server-side cap on
# `limitnum` (live-verified: 51+ is rejected outright). main hardcodes 100.
MAX_LIMITNUM = 50


def login(base: str) -> None:
    """Open a visible browser at `base`; the student signs in (their
    institution's own login page, SSO or not); save the session."""
    session.login(NAME, base)


def to_course(c: dict) -> Course:
    """core_enrol_get_users_courses (or a calendar event's own embedded
    `course` sub-object - same shape either way) -> Course. Moodle courses
    have no native "term"/section concept the way Canvas/Workday do.
    # ponytail: term left blank until a real response shows something usable
    # (category name? a custom course-info field?) to fill it from."""
    return Course(
        code=c.get("shortname", ""),
        section="",
        term="",
        title=c.get("fullname", ""),
        grade=None,  # gradereport_user_get_grade_items not implemented - see module docstring
        source=NAME,
    )


def to_item(e: dict) -> Item:
    """core_calendar_get_action_events_by_timesort event dict -> Item. Each
    event embeds its own course sub-object, so no separate course_id -> code
    lookup is needed. `url` is Moodle's own per-event link; when missing, we
    fall back to Moodle's real `calendar/event.php?id=<event id>` route keyed
    on the event's own id, never an empty url twice over (lauds' store
    upserts on `(source, url)`)."""
    course = e.get("course") or {}
    kind = KINDS.get(e.get("modulename", ""), "assignment")
    timesort = e.get("timesort")
    event_id = e.get("id")
    return Item(
        course=course.get("shortname", ""),
        category=category_for(kind),
        kind=kind,
        title=e.get("name", ""),
        due=datetime.fromtimestamp(timesort, tz=timezone.utc) if timesort else None,
        url=e.get("url") or f"calendar/event.php?id={event_id}",
        source=NAME,
        description=e.get("description") or None,
    )


def extract_sesskey(page_text: str) -> str | None:
    """Dashboard page text -> the `M.cfg.sesskey` value, or None if it isn't
    there (session isn't actually logged in)."""
    m = SESSKEY_RE.search(page_text)
    return m.group(1) if m else None


def _sesskey(req, base: str) -> str:
    r = req.get(f"{base}/my/")  # dashboard: always rendered for a logged-in user
    if r.status == 401:
        raise session.NotLoggedIn(base)
    if not r.ok:
        raise RuntimeError(f"{base}/my/ -> {r.status}")
    key = extract_sesskey(r.text())
    if key is None:
        raise session.NotLoggedIn(base)  # no sesskey on the page => not actually logged in
    return key


def _ajax_call(req, base: str, sesskey: str, methodname: str, args: dict):
    """POST exactly one call to Moodle's internal AJAX multiplexer
    (`/lib/ajax/service.php`, the same call shape Moodle's own `core/ajax` JS
    module uses) and return its `data`. Never batched with another call - see
    module docstring, bug #1: a function without `'ajax' => true` aborts the
    *whole* batch, taking down every other call in it. Raises RuntimeError if
    Moodle reports an error for this call."""
    payload = [{"index": 0, "methodname": methodname, "args": args}]
    r = req.post(f"{base}/lib/ajax/service.php?sesskey={sesskey}&info={methodname}",
                 data=json.dumps(payload), headers={"Content-Type": "application/json"})
    if r.status == 401:
        raise session.NotLoggedIn(base)
    if not r.ok:
        raise RuntimeError(f"lib/ajax/service.php ({methodname}) -> {r.status}")
    (result,) = json.loads(r.text())
    if result.get("error"):
        message = (result.get("exception") or {}).get("message", "moodle ajax error")
        raise RuntimeError(f"{methodname}: {message}")
    return result.get("data")


def _courses_from_events(events: list[dict]) -> list[Course]:
    """Fallback course list built from each event's own embedded `course`
    sub-object, de-duplicated by shortname, in first-seen order. Used when
    `core_enrol_get_users_courses` can't be reached (module docstring, bug
    #1) - real data this adapter already fetches for items, beats returning
    no courses at all."""
    seen: set[str] = set()
    courses = []
    for e in events:
        c = e.get("course") or {}
        code = c.get("shortname")
        if code and code not in seen:
            seen.add(code)
            courses.append(to_course(c))
    return courses


def _run(req, base: str, start: int, end: int) -> tuple[list[Course], list[Item]]:
    sesskey = _sesskey(req, base)
    calendar = _ajax_call(req, base, sesskey, "core_calendar_get_action_events_by_timesort",
                           {"timesortfrom": start, "timesortto": end, "limitnum": MAX_LIMITNUM})
    events = (calendar or {}).get("events", [])
    items = [to_item(e) for e in events]
    try:
        raw_courses = _ajax_call(req, base, sesskey, "core_enrol_get_users_courses", {"userid": 0})
        courses = [to_course(c) for c in raw_courses or []]
    except RuntimeError:
        # [known Moodle-core limitation, live-verified] - see module docstring, bug #1.
        courses = []
    if not courses:
        courses = _courses_from_events(events)
    return courses, items


def fetch(base: str, start: int | None = None, end: int | None = None) -> Bundle:
    """Return a Bundle for `base` (a Moodle site's own URL - unlike Canvas,
    Moodle isn't one fixed host, so every caller supplies it). Opens a
    browser window to log in if there's no saved session for it."""
    now = datetime.now(timezone.utc)
    start = start if start is not None else int(now.timestamp() - 120 * 86400)
    end = end if end is not None else int(now.timestamp() + 120 * 86400)
    courses, items = session.fetch_with_session(NAME, base, lambda req: _run(req, base, start, end))
    return Bundle(courses=courses, items=items)


def parse_capture(capture: dict) -> tuple[list[Course], list[Item]]:
    """Map the experimental extension's minimal Moodle JSON via this
    adapter's own mapper - same URL-safety checks as main (https-only,
    same-origin, no userinfo, and an event's own id must be numeric before it
    can stand in for a missing url)."""
    if not isinstance(capture, dict) or capture.get("source") != NAME:
        raise ValueError("expected Moodle capture")
    origin = capture.get("origin")
    parsed_origin = urlparse(origin) if isinstance(origin, str) else None
    if (not parsed_origin or parsed_origin.scheme != "https" or not parsed_origin.netloc
            or parsed_origin.path or parsed_origin.query or parsed_origin.fragment
            or parsed_origin.username or parsed_origin.password):
        raise ValueError("invalid Moodle origin")
    raw_courses, events = capture.get("courses"), capture.get("events")
    if (not isinstance(raw_courses, list) or not isinstance(events, list)
            or len(raw_courses) > 100 or len(events) > 1000
            or any(not isinstance(row, dict) for row in raw_courses + events)):
        raise ValueError("invalid Moodle capture")
    items = []
    for event in events:
        event = dict(event)
        if not event.get("url"):
            event_id = event.get("id")
            if not str(event_id).isdigit():
                raise ValueError("Moodle event has no safe URL")
            event["url"] = urljoin(origin, f"/calendar/event.php?id={event_id}")
        url = urlparse(event["url"])
        query = parse_qsl(url.query, keep_blank_values=True)
        if (url.scheme != "https" or url.netloc != parsed_origin.netloc
                or url.username or url.password or url.fragment
                or any(key != "id" or not value.isdecimal() for key, value in query)):
            raise ValueError("Moodle event URL is unsafe")
        items.append(to_item(event))
    return [to_course(course) for course in raw_courses], items
