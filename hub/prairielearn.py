"""PrairieLearn adapter: browser-session login (hub.site), then scrape each
enrolled course's Assessments page for tasks/deadlines. No student-facing
API exists (docs/api-standards.md), so this reads the same HTML a student
sees, same as Canvas's browser-login path reads its JSON.

Verified against a real UBC course (CPSC 317, 2026 Winter Term 1). Two real
limitations, not guessed:
- PrairieLearn has no single "due date" - each assessment has a multi-tier
  credit schedule (100% until X, 70% until Y, ...). We take the end of the
  100%-credit tier as `due`, same meaning as "due date" for a student.
- An assessment PrairieLearn hasn't opened yet shows only "Available <time>,
  <weekday>, <month> <day>" (no year, no tier table) - not enough to build an
  exact datetime. Those come back with `due=None` rather than a guess.

Try it:  uv run python -m hub.prairielearn
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup

from hub import site
from hub.models import Course, Item, category_for

BASE = "https://us.prairielearn.com"
SITE = "prairielearn"

# UBC courses only ever show Pacific time. Fixed offsets, not zoneinfo/pytz:
# good enough while every course we've seen is UBC; add zones if that changes.
# "MST" included for BC's 2027-01-06 permanent-DST tzdata change (see
# tests/test_db.py): once BC stops changing clocks, tzdata names the resulting
# fixed UTC-7 offset "MST" (it coincides with Mountain Standard Time), even
# though it's still what PrairieLearn shows as "Vancouver time".
TZ_OFFSET = {"PST": -8, "PDT": -7, "MST": -7}

# PrairieLearn groups assessments under headings an instructor names freely
# ("Programming Assignments", "Tutorial", ...); these are the ones we've seen
# that mean something other than a plain task. Unlisted -> "assignment".
KIND_FOR_GROUP = {
    "practice for quizzes": "quiz",
    "quizzes": "quiz",
    "formal quizzes": "exam",
    "formal quizzes (repeated for practice)": "exam",
    "exams": "exam",
}

COURSE_TITLE = re.compile(r"([A-Z]+ ?\d+\w*):\s*(.+),\s*(\d{4} \w+ Term \d+)")


def login():
    """Open a visible browser; the student signs in (UBC CWL); we save the session."""
    site.login(SITE, BASE)


def _get_soup(req, path):
    r = req.get(f"{BASE}{path}")
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return BeautifulSoup(r.text(), "html.parser")


def to_course(ci_id, title):
    m = COURSE_TITLE.match(title)
    if not m:  # ponytail: title format changed/unexpected - keep the raw text rather than crash
        return Course(code=title, section="", term="", title=title)
    code, name, term = m.groups()
    return Course(code=code, section="", term=term, title=name)


def due_from_popover(popover_html):
    """The access-details popover's first row (100% credit) -> its end time,
    timezone-aware (same as Canvas's due dates - never mix naive and aware
    datetimes in the shared model). None if there's no popover yet (assessment
    not open, see module docstring)."""
    if not popover_html:
        return None
    rows = BeautifulSoup(popover_html, "html.parser").select("tr")[1:]  # skip Credit/Start/End header
    if not rows:
        return None
    end = rows[0].select("td")[2].get_text(strip=True)  # "2026-09-27 23:59:59 (PDT)" or "—"
    return due_from_end_text(end)


def due_from_end_text(end):
    """Parse the first 100%-credit end text from either adapter input path."""
    m = re.match(r"(.+) \(([A-Z]+)\)$", end)
    if not m:
        return None
    dt_str, tz = m.groups()
    if tz not in TZ_OFFSET:
        # Silently treating an unrecognized abbreviation as UTC used to be a
        # 7h-off bug waiting to happen (#15) - fail loud instead.
        raise ValueError(f"unrecognized PrairieLearn timezone abbreviation: {tz!r}")
    return datetime.fromisoformat(dt_str).replace(tzinfo=timezone(timedelta(hours=TZ_OFFSET[tz])))


_SCORE_RE = re.compile(r"([\d.]+)\s*%")


def done_from_score(cells):
    """PrairieLearn has no submitted/graded flag of its own on this page -
    the 4th column shows a percentage ("100%") once attempted, or a status
    like "Not started"/"Not yet released" otherwise. A 100% score is one
    heuristic for "nothing left to do here" (a lower score is still
    improvable up until the assessment closes - see done_from_credit for the
    other case, a closed assessment whose score never reached 100%)."""
    if len(cells) < 4:
        return None
    return done_from_score_text(cells[3].get_text(strip=True))


def done_from_score_text(score_text):
    m = _SCORE_RE.search(score_text)
    return m is not None and float(m.group(1)) >= 100


def done_from_credit(cells):
    """Once an assessment's whole credit schedule has expired, the Available
    Credit column (3rd) shows nothing at all - no popover, no "Available
    <time>" notice - since there's nothing left that could still change the
    score. Verified against a real UBC course: several closed assessments
    show this with a score well under 100% (e.g. 66%, 80%, 85%), which
    done_from_score alone would miss. A not-yet-open assessment always shows
    an "Available <time>" message instead, so this never collides with that
    case.

    An empty credit cell alone isn't enough, though (PM review on #15/#71
    found this live): PrairieLearn also shows an empty cell for an
    assessment that still accepts 0%-credit "practice" submissions after its
    last deadline (`afterLastDeadline.allowSubmissions=true, credit=0`) -
    that's not finished, just not worth more points anymore. Require a
    nonzero score too, so a never-attempted assessment in that state stays
    visible instead of silently disappearing."""
    if len(cells) < 4:
        return False
    credit_cell = cells[2]
    return done_from_credit_fields(
        credit_cell.find("button") is None and credit_cell.get_text(strip=True) == "",
        cells[3].get_text(strip=True),
    )


def done_from_credit_fields(credit_empty, score_text):
    if not credit_empty:
        return False
    m = _SCORE_RE.search(score_text)
    return m is not None and float(m.group(1)) > 0


def _item_from_fields(*, title, group, ci_id, course_code, href, due_text, score_text,
                      credit_empty):
    kind = KIND_FOR_GROUP.get(group.strip().lower(), "assignment")
    url = f"{BASE}{href}" if href else f"{BASE}/pl/course_instance/{ci_id}/assessments#{quote(title)}"
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=title,
        due=due_from_end_text(due_text) if due_text else None,
        url=url,
        source=SITE,
        done=bool(done_from_score_text(score_text)) or done_from_credit_fields(credit_empty, score_text),
    )


def to_item(row, course_code, group, ci_id):
    cells = row.select("td")
    link = cells[1].find("a")
    popover = cells[2].find("button")
    title = cells[1].get_text(strip=True)
    # An assessment PrairieLearn hasn't opened yet has no link (module
    # docstring), so url="" used to be its identity - every unreleased
    # assessment in every course collapsed onto one hub.db row (#15). Fall
    # back to the assessments page plus the title, unique enough within a
    # course and stable across re-fetches until the assessment actually opens.
    due_text = ""
    if popover:
        rows = BeautifulSoup(popover["data-bs-content"], "html.parser").select("tr")[1:]
        if rows:
            due_text = rows[0].select("td")[2].get_text(strip=True)
    return _item_from_fields(
        title=title, group=group, ci_id=ci_id, course_code=course_code,
        href=link["href"] if link else "", due_text=due_text,
        score_text=cells[3].get_text(strip=True) if len(cells) > 3 else "",
        credit_empty=(cells[2].find("button") is None and cells[2].get_text(strip=True) == ""),
    )


def parse_capture(capture):
    """Map selected assessment fields through the existing PrairieLearn rules."""
    # ponytail: PrairieLearn-only rule-6 DOM exception; use a student JSON API
    # if PrairieLearn offers one. This function never parses uploaded HTML.
    if not isinstance(capture, dict) or capture.get("source") != SITE:
        raise ValueError("expected PrairieLearn capture")
    if capture.get("origin") != BASE:
        raise ValueError("invalid PrairieLearn origin")
    raw_courses = capture.get("courses")
    if (not isinstance(raw_courses, list) or len(raw_courses) > 100
            or any(not isinstance(course, dict) for course in raw_courses)):
        raise ValueError("invalid PrairieLearn courses")
    courses, items = [], []
    for raw in raw_courses:
        ci_id, title, assessments = raw.get("ci_id"), raw.get("title"), raw.get("assessments")
        if (not isinstance(ci_id, str) or not ci_id.isdecimal()
                or not isinstance(title, str) or not title
                or not isinstance(assessments, list) or len(assessments) > 300):
            raise ValueError("invalid PrairieLearn course")
        if not COURSE_TITLE.match(title):
            continue  # Same example-course filter as _run().
        course = to_course(ci_id, title)
        courses.append(course)
        for row in assessments:
            if not isinstance(row, dict):
                raise ValueError("invalid PrairieLearn assessment")
            href = row.get("href", "")
            if (not isinstance(href, str) or href and not re.fullmatch(
                    rf"/pl/course_instance/{ci_id}/assessment_instance/\d+/?", href)):
                raise ValueError("unsafe PrairieLearn assessment URL")
            fields = ("title", "group", "due_text", "score_text")
            if (any(not isinstance(row.get(field, ""), str) for field in fields)
                    or not row.get("title")):
                raise ValueError("invalid PrairieLearn assessment fields")
            if not isinstance(row.get("credit_empty", False), bool):
                raise ValueError("invalid PrairieLearn credit status")
            items.append(_item_from_fields(
                title=row.get("title", ""), group=row.get("group", ""),
                ci_id=ci_id, course_code=course.code, href=href,
                due_text=row.get("due_text", ""), score_text=row.get("score_text", ""),
                credit_empty=row.get("credit_empty", False),
            ))
    return courses, items


_CI_LINK = re.compile(r"^/pl/course_instance/(\d+)(?:/instructor)?/?$")


def _course_instances(req):
    """[(id, display title)] for every course on the student's home page.

    Matches both the student link (.../course_instance/<id>) and the
    instructor one (.../course_instance/<id>/instructor) - TAs/instructors
    used to see zero courses because only the student shape matched (#15).
    # ponytail: this still reads the student Assessments page for everyone
    (_assessments below), which may not be right for an instructor-only
    account - untested without a real TA login. Revisit if that's wrong."""
    soup, seen, out = _get_soup(req, "/"), set(), []
    for a in soup.select("a[href^='/pl/course_instance/']"):
        m = _CI_LINK.match(a["href"])
        if not m or m[1] in seen:
            continue
        seen.add(m[1])
        out.append((m[1], a.get_text(strip=True)))
    return out


def _assessments(req, ci_id, course_code):
    soup = _get_soup(req, f"/pl/course_instance/{ci_id}/assessments")
    items, group = [], ""
    for row in soup.select("table tbody tr"):
        heading = row.find("th")
        if heading:
            group = heading.get_text(strip=True)
        else:
            items.append(to_item(row, course_code, group, ci_id))
    return items


def fetch():
    """Return (courses, items) for every course on the student's PrairieLearn
    home page. Opens a browser window to log in if there's no saved session."""
    return site.fetch_with_session(SITE, BASE, _run)


def _run(req):
    courses, items = [], []
    for ci_id, title in _course_instances(req):
        if not COURSE_TITLE.match(title):
            # ponytail: skip instances that don't look like a UBC course code -
            # this is also what filters out PrairieLearn's own built-in example
            # course, which the wider instructor-link matching above now finds
            # too and would otherwise show up as a phantom "Spring 2015" course
            # (#15). Upgrade: ask PL for real course metadata if that's ever
            # exposed, instead of sniffing the title.
            continue
        course = to_course(ci_id, title)
        courses.append(course)
        items += _assessments(req, ci_id, course.code)
    return courses, items


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:10} {c.term:20} {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or datetime.max)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:10} {i.title}")
