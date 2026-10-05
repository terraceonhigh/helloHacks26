"""WeBWorK adapter: browser-session login (hub.site), then scrape a course's
problem-set list page for tasks/deadlines.

**Verified against a real UBC course** (MATH_V 100A ALL SECTIONS 2026W1,
reached via UBC's self-hosted webwork.elearning.ubc.ca, 2026-09-26) -- the
markup below is the actual page, not a guess. Two things about that real
course carry over as genuine constraints, not just guesses:

- **No standalone login here.** This deployment has no separate
  username/password form; the WeBWorK session is established by launching
  the course's "WeBWorK" link from Brightspace (LTI SSO), which lands you
  on `base` already logged in. Once that session cookie exists, plain GETs
  to `base` work fine on their own (no LTI relaunch needed per page) --
  confirmed by navigating there directly in a fresh tab and seeing "Logged
  in as ..." with the full assignment list, no login prompt. `hub.site`'s
  own `login()` (open `base`, wait for the student to sign in, save the
  session) is therefore UNVERIFIED for WeBWorK specifically: we don't know
  what a cookie-less hit to `base` looks like for a school that only offers
  WeBWorK via LTI. Schools where WeBWorK *does* front its own login page
  should work fine with `hub.site.login` same as Canvas/PrairieLearn.
- **The due date disappears once a set closes.** WeBWorK's default
  Assignments listing shows a due date only for currently-open sets
  ("Open. Due <date>."). A set that hasn't opened yet shows only its open
  date ("Will open on <date>.") -- no due date at all. A set that's past
  due shows only "Answers available for review[ on <date>]." -- that date
  is when *answers* unlock, not the original due date, and is NOT the same
  thing. This adapter does not fabricate a due date for either case; both
  come back with `due=None`, honestly reflecting what the page shows.
- **No score/completion signal exists on this page at all.** There's no
  score or percentage anywhere in the Assignments listing (a separate
  Grades page exists, linked in the nav, but wasn't explored -- a
  cross-reference against it would be a real future improvement, not
  something to guess at here). Every Item's `done` is `None` (unknown).

Why this exists (see issue #23): at UBC, WeBWorK sets are usually embedded in
Canvas as an "External Tool" assignment, so hub/canvas.py likely already
lists them -- but grades sync to Canvas roughly daily and due dates don't
sync at all (the instructor types the Canvas date in by hand, so it can
drift). This adapter exists for two cases: (1) correcting that drift by
reading WeBWorK's own due date for currently-open sets, and (2) schools that
run WeBWorK standalone with no LMS in front of it at all (this project's
"other schools too" mission, per AGENTS.md).

Try it:  uv run python -m hub.webwork <course-url> <course-code>
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from hub import site
from hub.models import Course, Item, category_for

SITE = "webwork"

# Common North American zone abbreviations WeBWorK's date strings show (a
# real one, "PDT", is confirmed; the rest are the same educated extension
# hub/prairielearn.py makes, kept only until a course in a different zone
# shows up).
TZ_OFFSET = {
    "PST": -8, "PDT": -7,
    "MST": -7, "MDT": -6,
    "CST": -6, "CDT": -5,
    "EST": -5, "EDT": -4,
}

# The real, verified format: "October 1, 2026, 11:59:00 PM PDT." (full month
# name, comma-separated, seconds included, then a zone abbreviation).
DATE_RE = re.compile(
    r"(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4}),\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})\s*(?P<ampm>AM|PM)\s+(?P<tz>[A-Z]{2,4})",
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def login(base):
    """Open a visible browser at the course's WeBWorK URL; the student signs
    in if there's a login form to sign in to. See the module docstring's
    login caveat -- for an LTI-only deployment, this needs the student to
    have already reached `base` once via their LMS."""
    site.login(SITE, base)


def _get_soup(req, url):
    r = req.get(url)
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{url} -> {r.status}")
    return BeautifulSoup(r.text(), "html.parser")


def due_from_text(text):
    """Parse a real WeBWorK date string ("October 1, 2026, 11:59:00 PM PDT")
    into a tz-aware datetime, or None if there's no such date in `text`."""
    if not text:
        return None
    m = DATE_RE.search(text)
    if not m:
        return None
    month = _MONTHS.get(m.group("month").lower())
    if month is None:
        return None
    hour = int(m.group("hour")) % 12
    if m.group("ampm").upper() == "PM":
        hour += 12
    dt = datetime(int(m.group("year")), month, int(m.group("day")), hour, int(m.group("minute")), int(m.group("second")))
    offset = TZ_OFFSET.get(m.group("tz").upper(), 0)
    return dt.replace(tzinfo=timezone(timedelta(hours=offset)))


def to_item(li, course_code, base=""):
    """One real <li data-set-status="open|not-open|past-due"> -> an Item.

    Verified structure: a title (an <a class="fw-bold ..."> when the set has
    a link -- open or past-due -- or a plain <span class="set-id-tooltip">
    when it doesn't -- not yet open), followed by a `<div class="font-sm">`
    holding the status/date text described in the module docstring. `base`
    resolves a relative href into an absolute URL; pass "" in tests where
    the exact host doesn't matter.

    A not-yet-open set has no real link yet, but `hub.db`'s items table
    upserts on `(source, url)` (AGENTS.md rule 4) -- an empty `url` would
    make every not-yet-open set in a course collide and overwrite each
    other, so one is synthesised from the set's own name instead.
    """
    status = li.get("data-set-status", "")
    link = li.select_one("a.fw-bold, div.ms-3 a")
    if link is not None:
        title = link.get_text(strip=True)
        url = urljoin(base, link["href"]) if link.get("href") else ""
    else:
        name_el = li.select_one("span.set-id-tooltip")
        title = name_el.get_text(strip=True) if name_el else li.get_text(strip=True)
        # A not-yet-open set has no link at all (verified: WW4 above has no
        # <a>). But hub.db's items table is UNIQUE(source, url) and upserts
        # on that pair (AGENTS.md rule 4) -- leaving `url` blank here would
        # make every not-yet-open set in a course collide on ("webwork", "")
        # and silently overwrite each other. Build the same base+"/"+name
        # shape the real open/past-due links already use, so each set still
        # gets a distinct, stable identity even before it has a real link.
        url = urljoin(base.rstrip("/") + "/", quote(title, safe="")) if title else ""

    status_el = li.select_one("div.font-sm")
    status_text = status_el.get_text(" ", strip=True) if status_el else ""
    # Only an *open* set's status line contains its real due date -- see the
    # module docstring. A not-open or past-due set's date (if any) is a
    # different date entirely, not the due date, so it's deliberately not
    # parsed as one here.
    due = due_from_text(status_text) if status == "open" else None

    # data-set-type="test" for quizzes is inferred, not directly observed:
    # the real course had none, only "Regular Assignment"s (data-set-type=
    # "default"). The inference comes from the page's own "Show By Type"
    # toggle, whose data attributes read data-default-title="Regular
    # Assignments" / data-test-title="Tests/Quizzes" -- a strong hint, not
    # a confirmed value. Update this comment once a real quiz set is seen.
    kind = "quiz" if li.get("data-set-type") == "test" else "problemset"

    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=title,
        due=due,
        url=url,
        source=SITE,
        done=None,  # no score/completion signal exists on this page -- see module docstring
    )


def _problem_sets(req, base, course_code):
    soup = _get_soup(req, base)
    items = []
    # The real markup is <li data-set-status="..."> inside
    # #set-list-container, not a <table> -- skip anything without that
    # attribute rather than assuming every <li> on the page is a set.
    for li in soup.select("li[data-set-status]"):
        items.append(to_item(li, course_code, base))
    return items


def fetch(base, course_code):
    """Return items for the WeBWorK course at `base` (e.g.
    "https://webwork.example.edu/webwork2/math101"). `course_code` is
    supplied by the caller -- there's no student-facing course-catalogue
    join key on this page -- so items can be matched against the same
    course from Canvas/Workday. Opens a browser window to log in if there's
    no saved session (see the module docstring's login caveat)."""
    return site.fetch_with_session(SITE, base, lambda req: _problem_sets(req, base, course_code))


if __name__ == "__main__":
    import sys

    from hub import db

    if len(sys.argv) < 3:
        print("usage: uv run python -m hub.webwork <course-url> <course-code>")
        raise SystemExit(1)
    course_url, course_code = sys.argv[1], sys.argv[2]
    items = fetch(course_url, course_code)
    db.save(db.connect(), [Course(code=course_code, section="", term="", title=course_code)], items)
    for i in sorted(items, key=lambda i: (i.due is None, i.due or datetime.max)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:10} {i.title}")
