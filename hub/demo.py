"""Zero-click demo: a made-up student ("Stu Dent") run through the real adapters.

The hosted site (web/, Sample mode) has no login and no database, but it
should still show what Hub actually does - so instead of hand-typed sample
rows, demo_rows() replays saved, fake provider responses
(hub/demo_fixtures/) through the same functions a live fetch uses:

- Canvas: canvas._run() over an in-memory transport serving /api/v1 JSON
  (courses, planner/items, per-course assignments)
- Canvas calendar feed: ics.parse() over a .ics file
- PrairieLearn: prairielearn._run() over the same transport serving HTML
- WeBWorK: webwork._problem_sets() over its Assignments page HTML
- Brightspace: brightspace._run() over whoami + myenrollments JSON
- Piazza: piazza._run() over user.status / get_my_feed / content.get RPC JSON
- Workday: workday.parse_workday_courses() and parse_workday_schedule()
  over a "View My Courses" .xlsx export
- UBC Bookstore: bookstore._parse_sections() / _parse_textbooks() over its
  public section-list and CourseSearch pages
- UBC key dates: key_dates.fetch()

then fuses them the way hub/api.py's /api/upcoming does (logic.dedupe,
status_of, sort_items, api._row_to_dict). No network, browser or database:
the transport below only reads files next to this module.

One whole term, always "mid-term": `now` sits in week 5 of a 13-week term
plus a 2-week exam period. Fixture dates are stored as tokens and rendered
into each provider's own date format at request time, so the demo never
goes stale:

- {{due:+2d@23:59}}    two days from today, 23:59 Vancouver time
- {{due:w6.Tue@18:00}} term week 6's Tuesday, 18:00 Vancouver time (week
  1's Monday is the Monday four weeks before this week's)
- {{date:w1.Tue}}      that day as YYYY-MM-DD (Workday's term dates)
- a trailing |fmt picks another on-page format than the file's own
  (PrairieLearn's "Available 09:00, Mon, Oct 12" notice)

Things near `now` use +Nd offsets, so what's overdue or due soon is the
same whatever weekday the demo is opened on; week-5 week tokens are only
used for items that are already done, for the same reason.

Everything in hub/demo_fixtures/ is fake: no real student, instructor,
course content or course URL. Canvas links point at canvas.example.edu and
WeBWorK/Brightspace at *.example.edu; the transport never goes online.
"""
import io
import json
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import openpyxl

from hub import (api, bookstore, brightspace, canvas, ics, key_dates, piazza, prairielearn,
                 webwork, workday)
from hub.db import _canonical_code, _canonical_term
from hub.logic import dedupe, normalise_course_code, sort_items
from hub.models import status_of

FIXTURES = Path(__file__).parent / "demo_fixtures"
VAN = ZoneInfo("America/Vancouver")
TERM = "2026W1"
NOW_WEEK = 5  # the week of the 13-week term `now` always falls in
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_TOKEN = re.compile(
    r"\{\{(due|date):(?:([+-]\d+)d|w(\d+)\.(Mon|Tue|Wed|Thu|Fri|Sat|Sun))"
    r"(?:@(\d{2}):(\d{2}))?(?:\|(\w+))?\}\}")

# The demo student's own course sites - fake hosts, never contacted.
WEBWORK_BASE = "https://webwork.example.edu/webwork2/MATH100_2026W1/"
WEBWORK_COURSE = "MATH_V 100A ALL SECTIONS 2026W1"  # the Brightspace course WeBWorK launches from
BRIGHTSPACE_BASE = "https://brightspace.example.edu"
BOOKSTORE_PROGRAMS = ("CPSC", "PHYS", "ENGL")


def term_week1(now):
    """Monday of term week 1: NOW_WEEK - 1 weeks before this week's Monday."""
    today = now.astimezone(VAN).date()
    return today - timedelta(days=today.weekday(), weeks=NOW_WEEK - 1)


def _day(m, now):
    if m[2] is not None:
        return now.astimezone(VAN).date() + timedelta(days=int(m[2]))
    return term_week1(now) + timedelta(weeks=int(m[3]) - 1, days=_WEEKDAYS.index(m[4]))


# Each provider's own on-the-wire date format, so its real parser does the parsing.
_FORMATS = {
    "canvas": lambda dt: dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "ics": lambda dt: dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    "prairielearn": lambda dt: f"{dt:%Y-%m-%d %H:%M:%S} ({dt.tzname()})",
    # An assessment that hasn't opened yet (no year; the adapter doesn't parse it).
    "pl_available": lambda dt: f"Available {dt:%H:%M}, {dt:%a}, {dt:%b} {dt.day}",
    # "October 1, 2026, 11:59:00 PM PDT" - hub/webwork.py's verified shape.
    "webwork": lambda dt: f"{dt:%B} {dt.day}, {dt.year}, {dt:%I:%M:%S %p} {dt.tzname()}",
}


def _sub(text, fmt, now):
    def one(m):
        day = _day(m, now)
        if m[1] == "date":
            return day.isoformat()
        dt = datetime.combine(day, time(int(m[5] or 23), int(m[6] or 59)), tzinfo=VAN)
        return _FORMATS[m[7] or fmt](dt)
    return _TOKEN.sub(one, text)


def _render(name, fmt, now):
    return _sub((FIXTURES / name).read_text(), fmt, now)


def _render_xlsx(name, now):
    """The Workday export with its date tokens filled in, as in-memory .xlsx
    bytes - the same kind of file a student downloads, so hub/workday.py
    reads it exactly as it reads a real one."""
    wb = openpyxl.load_workbook(FIXTURES / name)
    for ws in wb:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and "{{" in cell.value:
                    cell.value = _sub(cell.value, "canvas", now)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


class _Response:
    def __init__(self, body, status=200):
        self.status, self.ok, self.headers, self._body = status, 200 <= status < 300, {}, body
        # The URL this answers, like a real Playwright response carries -
        # stamped by _FixtureRequest below. Adapters read it to tell a real
        # page from an SSO login page they were redirected to (hub/webwork.py).
        self.url = ""

    def text(self):
        return self._body

    def json(self):
        return json.loads(self._body)


# The demo student is on PrairieLearn's default campus - same key/base a
# real hub.prairielearn.fetch() with no argument resolves to.
_PL_KEY, _PL_BASE = prairielearn.resolve_campus(prairielearn.DEFAULT_CAMPUS)


class _FixtureRequest:
    """Stands in for the logged-in browser session hub.site hands an
    adapter's _run(): same .get(url) / .post(url, data=...) -> response
    interface, but every URL is answered from hub/demo_fixtures/ instead of
    the network."""

    def __init__(self, now):
        self.now = now

    def _file(self, name, fmt):
        return _Response(_render(name, fmt, self.now))

    def get(self, url):
        # A fixture never redirects, so the answer is always for the URL that
        # was asked for - stamp it so adapters that compare the two (checking
        # they weren't bounced to a login page) see a match.
        r = self._get(url)
        r.url = url
        return r

    def _get(self, url):
        parsed = urlparse(url)
        host, path = parsed.hostname, parsed.path.rstrip("/")
        if host == urlparse(canvas.BASE).hostname:
            if path == "/api/v1/courses":
                return self._file("canvas_courses.json", "canvas")
            if path == "/api/v1/planner/items":
                return self._file("canvas_planner_items.json", "canvas")
            m = re.fullmatch(r"/api/v1/courses/(\d+)/assignments", path)
            if m:
                by_course = json.loads(_render("canvas_assignments.json", "canvas", self.now))
                return _Response(json.dumps(by_course.get(m[1], [])))
        if host == urlparse(_PL_BASE).hostname:
            if path == "":
                return self._file("prairielearn_home.html", "prairielearn")
            m = re.fullmatch(r"/pl/course_instance/(\d+)/assessments", path)
            if m and (FIXTURES / f"prairielearn_assessments_{m[1]}.html").exists():
                return self._file(f"prairielearn_assessments_{m[1]}.html", "prairielearn")
        if url == WEBWORK_BASE:
            return self._file("webwork_math100.html", "webwork")
        if host == urlparse(BRIGHTSPACE_BASE).hostname:
            if path == "/d2l/api/lp/unstable/users/whoami":
                return self._file("brightspace_whoami.json", "canvas")
            if path == "/d2l/api/lp/1.50/enrollments/myenrollments":
                return self._file("brightspace_myenrollments.json", "canvas")
        return _Response("not in the demo fixtures", status=404)

    def post(self, url, data=None, headers=None):
        r = self._post(url, data=data, headers=headers)
        r.url = url
        return r

    def _post(self, url, data=None, headers=None):
        """Piazza's RPC endpoint: the method (and nid/cid) is in the JSON body."""
        if urlparse(url).hostname != urlparse(piazza.BASE).hostname:
            return _Response("not in the demo fixtures", status=404)
        rpc = json.loads((FIXTURES / "piazza_rpc.json").read_text())
        body = json.loads(data)
        params = body.get("params") or {}
        answer = rpc.get(body.get("method"))
        if body.get("method") == "network.get_my_feed":
            answer = answer.get(params.get("nid"))
        elif body.get("method") == "content.get":
            answer = answer.get(params.get("cid"))
        if answer is None:
            return _Response(json.dumps({"result": None, "error": "not in the demo fixtures"}))
        return _Response(json.dumps(answer))


def _textbooks(canvas_courses):
    """The Bookstore's public section list for each program the student
    takes, narrowed to their own sections - matched on the course code and
    section number inside Canvas's course codes, a cross-source join - then
    each section's CourseSearch page parsed into Textbooks.
    # ponytail: store links stay "" - bookstore.attach_store_links() scans
    # products.json straight through hub.net.get_text() with no injectable
    # transport, so it can't be replayed offline. Upgrade: give it a `get`
    # parameter like hub.site's adapters take.
    """
    enrolled = set()
    for c in canvas_courses:
        faculty, number, section = normalise_course_code(c.code)
        if faculty and number and section:
            enrolled.add((f"{faculty} {number}", section))
    books = []
    for program in BOOKSTORE_PROGRAMS:
        for s in bookstore._parse_sections((FIXTURES / f"bookstore_sections_{program}.html").read_text()):
            course = bookstore._course_from_section(s, TERM)
            page = FIXTURES / f"bookstore_textbooks_{s['code']}_{s['section']}.html"
            if (course.code, s["section"]) in enrolled and page.exists():
                books += bookstore._parse_textbooks(page.read_text(), course.code)
    return books


def _gather(now):
    """(courses, items, meetings, textbooks) from every demo provider,
    straight out of the real adapters - nothing fused yet. Canvas's API path
    and its calendar feed both run, as they would for a student who
    connected both."""
    req = _FixtureRequest(now)
    today = now.astimezone(VAN).date()
    export = _render_xlsx("workday_view_my_courses.xlsx", now)
    courses = workday.parse_workday_courses(io.BytesIO(export), TERM)
    meetings = workday.parse_workday_schedule(io.BytesIO(export), TERM)
    # WeBWorK ahead of Canvas: dedupe() keeps the first copy it sees, and
    # WeBWorK's own due date beats the hand-typed one on its Canvas mirror
    # (hub/webwork.py's docstring, #23).
    items = webwork._problem_sets(req, WEBWORK_BASE, WEBWORK_COURSE)
    c_courses, c_items = canvas._run(req, today - timedelta(days=120), today + timedelta(days=120))
    courses += c_courses
    items += c_items
    items += ics.parse(_render("canvas_calendar.ics", "ics", now), "canvas")
    for more_courses, more_items in (
            prairielearn._run(req, _PL_KEY, _PL_BASE),
            brightspace._run(req, BRIGHTSPACE_BASE),
            piazza._run(req, piazza.DEFAULT_POST_LIMIT),
            key_dates.fetch("UBCV", TERM, now=now)):
        courses += more_courses
        items += more_items
    return courses, items, meetings, _textbooks(c_courses)


def _fuse_courses(courses):
    """One row per canonical course code - the same merge hub.db.save()
    does (#41): shorter title wins, a known grade survives an unknown one.
    # ponytail: mirrors db._course_id() in memory because the demo mustn't
    # open a database; if that merge rule changes, change this with it.
    """
    fused = {}
    for c in courses:
        code, term = _canonical_code(c.code), _canonical_term(c.term)
        row = fused.setdefault(code, {"code": code, "term": term, "title": c.title, "grade": c.grade})
        row["term"] = row["term"] or term
        if len(c.title) < len(row["title"]):
            row["title"] = c.title
        if c.grade is not None:
            row["grade"] = c.grade
    return sorted(fused.values(), key=lambda r: r["code"])


def _row(item):
    """Item -> hub.db.upcoming()'s row shape, course code canonicalised the
    way save() joins it, so api._row_to_dict() serialises it unchanged."""
    return (_canonical_code(item.course), item.category, item.kind, item.title,
            item.due.isoformat() if item.due else None, item.url, item.done, item.source)


def _meeting(m):
    """Meeting -> hub/api.py's /api/schedule row shape."""
    return {"course": _canonical_code(m.course), "kind": m.kind, "days": list(m.days),
            "start_time": m.start_time.strftime("%H:%M"), "end_time": m.end_time.strftime("%H:%M"),
            "location": m.location, "term_start": m.term_start.isoformat(),
            "term_end": m.term_end.isoformat(), "source": m.source}


def demo_rows(now=None):
    """The whole demo dashboard as JSON-ready data: {"demo": true, "items":
    [...] (ranked, /api/upcoming's shape), "announcements": [...]
    (/api/announcements' shape), "courses": [...] (/api/courses' shape),
    "schedule": [...] (/api/schedule's shape), "textbooks": [...]}."""
    now = now or datetime.now(timezone.utc)
    courses, items, meetings, textbooks = _gather(now)
    # Canonicalise course codes first so dedupe() sees Canvas's
    # "CPSC_V 110-101 2026W1" and PrairieLearn's "CPSC 110" as one course -
    # hub.db does the same when it joins items to course rows.
    for i in items:
        i.course = _canonical_code(i.course)
    items = dedupe(items)
    # dedupe() keys on (course, title, due); rule 4's (source, url) identity is
    # the other half - the db upsert. Same key, first one seen wins.
    by_identity = {}
    for i in items:
        by_identity.setdefault((i.source, i.url), i)
    rows = [_row(i) for i in by_identity.values()]
    dated = [r for r in rows if r[4] and status_of(api._item_of(r), now) != "done"]
    upcoming = [api._row_to_dict(r, now) for r in sort_items(dated, now)]
    announcements = [api._row_to_dict(r, now) for r in rows if r[4] is None and r[2] == "announcement"]
    return {
        "demo": True, "items": upcoming, "announcements": announcements,
        "courses": _fuse_courses(courses),
        "schedule": [_meeting(m) for m in meetings],
        "textbooks": [{"course": _canonical_code(t.course), "title": t.title, "isbn": t.isbn,
                       "required": t.required, "price": t.price, "url": t.url} for t in textbooks],
    }
