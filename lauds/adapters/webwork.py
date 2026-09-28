"""WeBWorK adapter: browser-session login (lauds.session), then scrape a
course's problem-set list page for tasks/deadlines/quizzes.

Clean port of main's `hub/webwork.py` (behaviour kept, structure reworked
into the plugin protocol's split between pure parsing and network fetch).
Verified against a real UBC course (MATH_V 100A, webwork.elearning.ubc.ca,
2026-09-26) and against a self-hosted WeBWorK 2.21 on humboldt
(tests/oracle/webwork/live_selfhost.json) -- see grading in tests/live/.

Two real constraints carry over unchanged from that verification, not just
guesses:

- **No standalone login at some schools.** A school that only exposes
  WeBWorK via an LMS's LTI launch establishes the session cookie by
  visiting `base` through that LMS first; a plain GET to `base` afterwards
  works fine with no further login (confirmed live). `login()` below (open
  `base`, wait for the student to sign in, save the session) is UNVERIFIED
  for an LTI-only deployment: nothing here can drive an LTI relaunch.
  Schools where WeBWorK fronts its own login page work the same as
  Canvas/PrairieLearn. The self-hosted instance used for `live_selfhost`
  *does* have its own username/password + TOTP form (see
  tests/live/webwork_live.py), so `fetch_with_session`'s browser-login path
  is exercised there, just not the LTI-only path.
- **The due date only shows on an *open* set.** WeBWorK's Assignments list
  shows a due date only for a currently-open set ("Open. Due <date>.").
  A not-yet-open set shows only its open date ("Will open on <date>.") --
  never a due date. A past-due set shows only "Answers available for
  review[ on <date>]." -- that date is when *answers* unlock, not the
  original deadline. This adapter never fabricates a due date for either
  case: both come back with `due=None`. There is also no score/completion
  signal anywhere on this page (a separate Grades page exists but isn't
  scraped here), so `done` is always `None`.
- **The page's own timezone abbreviation must be honoured, not re-derived.**
  WeBWorK's Perl `DateTime::TimeZone` (bundled tzdata) predates BC's
  permanent-DST change and keeps printing "PST" (UTC-8) for Vancouver dates
  after the 2026-11-01 cutover, where a fresh tzdata's `America/Vancouver`
  would say something else. The server's stated instant is the one the
  student is held to, so `TZ_OFFSET` below is a fixed abbreviation->offset
  table, never `zoneinfo.ZoneInfo("America/Vancouver")` -- see
  tests/live/README.md's "PST-abbreviation-on-page rule" (confirmed live:
  tests/oracle/webwork/live_selfhost.json's January/2099 sets are "PST").

Why this exists (main's issue #23): WeBWorK sets embedded in an LMS as an
"External Tool" assignment often have grades/due-dates that drift out of
sync with the LMS's own copy (typed in by hand, synced roughly daily or
never); reading WeBWorK's own due date directly corrects that. It also
covers schools that run WeBWorK standalone with no LMS in front of it.
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from lauds import session
from lauds.models import Bundle, Item, category_for

NAME = "webwork"
DESCRIPTION = "WeBWorK problem sets (due dates, from the course's own Assignments page)"

# Common North American zone abbreviations WeBWorK's date strings show. Only
# "PST"/"PDT" are live-verified (see module docstring); the rest are the same
# educated extension main's adapter made, kept only until a course in another
# zone is actually seen. See the module docstring: never replace this with a
# real tzdata lookup -- the page's own abbreviation is authoritative.
TZ_OFFSET = {
    "PST": -8, "PDT": -7,
    "MST": -7, "MDT": -6,
    "CST": -6, "CDT": -5,
    "EST": -5, "EDT": -4,
    "UTC": 0, "GMT": 0,
}

# The verified format: "October 1, 2026, 11:59:00 PM PDT." (full month name,
# comma-separated, seconds included, then a zone abbreviation).
_DATE_RE = re.compile(
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4}),\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})\s*(?P<ampm>AM|PM)\s+(?P<tz>[A-Z]{2,4})",
)

_MONTHS = {name: n for n, name in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"], start=1)}


def due_from_text(text: str | None) -> datetime | None:
    """A real WeBWorK date string ("October 1, 2026, 11:59:00 PM PDT") ->
    a tz-aware datetime, honouring the page's own abbreviation (see module
    docstring). None if `text` holds no such date."""
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if month is None:
        return None
    hour = int(m.group("hour")) % 12
    if m.group("ampm").upper() == "PM":
        hour += 12
    dt = datetime(int(m.group("year")), month, int(m.group("day")), hour, int(m.group("minute")), int(m.group("second")))
    tz = m.group("tz").upper()
    if tz not in TZ_OFFSET:
        # Matches prairielearn.due_from_end_text's rule (BRIEF finding): an
        # unknown abbreviation silently mapping to UTC (AST/NST/AKST/HST, ...)
        # would be hours off with no error at all - better to fail loudly.
        raise ValueError(f"unrecognized WeBWorK timezone abbreviation: {tz!r}")
    return dt.replace(tzinfo=timezone(timedelta(hours=TZ_OFFSET[tz])))


def _synthetic_url(base: str, title: str) -> str:
    """A stable, distinct URL for a set with no real link yet (not-yet-open,
    no `<a>` on the page). lauds' store upserts items on (source, url)
    (like main's hub.db) -- a blank/shared URL would make every unopened set
    in a course collide and overwrite each other, so one is built from the
    set's own name instead, same shape the real open/past-due links use."""
    if not title:
        return ""
    return urljoin(base.rstrip("/") + "/", quote(title, safe=""))


def to_item(li, course_code: str, base: str = "") -> Item:
    """One `<li data-set-status="open|not-open|past-due">` tag (a bs4 Tag)
    -> an Item. `base` resolves a relative href into an absolute URL; pass
    "" where the exact host doesn't matter."""
    status = li.get("data-set-status", "")
    link = li.select_one("a.fw-bold, div.ms-3 a")
    if link is not None:
        title = link.get_text(strip=True)
        url = urljoin(base, link["href"]) if link.get("href") else ""
    else:
        name_el = li.select_one("span.set-id-tooltip")
        title = name_el.get_text(strip=True) if name_el else li.get_text(strip=True)
        url = _synthetic_url(base, title)

    status_el = li.select_one("div.font-sm")
    status_text = status_el.get_text(" ", strip=True) if status_el else ""
    # Only an *open* set's status line is a due date at all (see module
    # docstring) -- a not-open/past-due set's date, if any, is a different
    # date entirely and is deliberately never parsed as `due`.
    due = due_from_text(status_text) if status == "open" else None

    # data-set-type="test" for quizzes is an inference from the page's own
    # "Show By Type" toggle (data-test-title="Tests/Quizzes"), not something
    # directly observed on a real quiz set -- update this once one is seen.
    kind = "quiz" if li.get("data-set-type") == "test" else "problemset"

    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=title,
        due=due,
        url=url,
        source=NAME,
        done=None,  # no score/completion signal exists on this page -- see module docstring
    )


def parse_row(raw: str, course_code: str, base: str = "") -> Item:
    """Pure: one `<li data-set-status="...">` fragment (as raw HTML text,
    e.g. one parity fixture) -> an Item."""
    li = BeautifulSoup(raw, "html.parser").find("li")
    if li is None:
        raise ValueError("parse_row: no <li> found in the given fragment")
    return to_item(li, course_code, base)


def parse_problem_sets(raw: str, course_code: str, base: str = "") -> list[Item]:
    """Pure: a full Assignments-list page (raw HTML text) -> every set on
    it, in page order. The real markup is `<li data-set-status="...">`
    inside `#set-list-container`, not a `<table>` -- anything without that
    attribute is skipped rather than assumed to be a set."""
    soup = BeautifulSoup(raw, "html.parser")
    return [to_item(li, course_code, base) for li in soup.select("li[data-set-status]")]


def login(base, **opts):
    """Open a visible browser at the course's WeBWorK URL; the student
    signs in if there's a login form to sign in to. See the module
    docstring's login caveat -- for an LTI-only deployment, this needs the
    student to have already reached `base` once via their LMS."""
    session.login(NAME, base, **opts)


def looks_logged_out(html: str) -> bool:
    """True if `html` is WeBWorK's own login page, not the Assignments list.

    Live-verified (BRIEF finding): a logged-out `GET <course-url>/` still
    answers 200, not 401 - it silently serves `<form id="login_form">`
    instead of `#set-list-container`, which `parse_problem_sets` then reads
    as "zero sets" rather than a stale session (tests/fixtures/webwork/
    live_loggedout.html, captured against the self-hosted fake101 course)."""
    return 'id="login_form"' in html and "set-list-container" not in html


def fetch(base: str, course_code: str) -> Bundle:
    """Items for the WeBWorK course at `base` (e.g.
    "https://webwork.example.edu/webwork2/math101"). `course_code` is
    supplied by the caller -- there's no student-facing course-catalogue
    join key on this page -- so items can be matched against the same
    course from another adapter (Canvas, Workday, ...). Opens a browser
    window to log in if there's no saved session (see the login caveat)."""

    def _run(req):
        r = req.get(base)
        if r.status == 401:
            raise session.NotLoggedIn(base)
        if not r.ok:
            raise RuntimeError(f"{base} -> {r.status}")
        text = r.text()
        if looks_logged_out(text):
            raise session.NotLoggedIn(base)
        return Bundle(items=parse_problem_sets(text, course_code, base))

    return session.fetch_with_session(NAME, base, _run)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: python -m lauds.adapters.webwork <course-url> <course-code>")
        raise SystemExit(1)
    course_url, course_code = sys.argv[1], sys.argv[2]
    bundle = fetch(course_url, course_code)
    for i in sorted(bundle.items, key=lambda i: (i.due is None, i.due or datetime.max)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:10} {i.title}")
