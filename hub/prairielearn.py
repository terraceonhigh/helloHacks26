"""PrairieLearn adapter: browser-session login (hub.site), then scrape each
enrolled course's Assessments page for tasks/deadlines. No student-facing
API exists (docs/api-standards.md), so this reads the same HTML a student
sees, same as Canvas's browser-login path reads its JSON.

PrairieLearn is open-source and self-hostable by any department or
instructor, not just one deployment per school - a real student's MECH 260
assessments turned out to live on UBC Okanagan's own instance
(prairielearn.ok.ubc.ca), not the shared PrairieLearn SaaS
(us.prairielearn.com) their other courses used, and a search for "known UBC
PrairieLearn domains" turned up a *second*, independent UBC Okanagan
instance (pl.autoed.ok.ubc.ca, a single course's own AutoER tool) - so a
hardcoded list can never be complete. `campus` accepts either a known short
key (CAMPUSES) or a student-pasted "https://..." URL directly - see
resolve_campus(). Same open-source PrairieLearn codebase either way, so the
same scraping logic works against any of them - only the base URL and the
login session differ. Each campus gets its own saved session and its own
`source` value, so items from one never collide with another's.

Verified against a real UBC Vancouver course (CPSC 317, 2026 Winter Term 1).
# ponytail: prairielearn_ok, and any custom domain a student pastes in,
# haven't been verified against a real login - assumed identical markup
# since it's the same PrairieLearn codebase. Flag here if a real login
# shows different HTML.

Two real limitations, not guessed:
- PrairieLearn has no single "due date" - each assessment has a multi-tier
  credit schedule (100% until X, 70% until Y, ...). We take the end of the
  100%-credit tier as `due`, same meaning as "due date" for a student.
- An assessment PrairieLearn hasn't opened yet shows only "Available <time>,
  <weekday>, <month> <day>" (no year, no tier table) - not enough to build an
  exact datetime. Those come back with `due=None` rather than a guess.

Try it:  uv run python -m hub.prairielearn
"""
import ipaddress
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from hub import site
from hub.models import Course, Item, category_for

CAMPUSES = {
    "prairielearn": "https://us.prairielearn.com",
    "prairielearn_ok": "https://prairielearn.ok.ubc.ca",
}
DEFAULT_CAMPUS = "prairielearn"


def _is_ip_literal(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


# ipaddress.ip_address() only recognizes the canonical dotted-quad/full-IPv6
# forms - it rejects "127.1", "2130706433", "0x7f000001" and "017700000001"
# as not-an-IP, so _is_ip_literal() alone waves all of those through as
# "ordinary hostnames". A browser's URL parser (what Playwright actually
# navigates with) accepts every one of those as an alternate IPv4 notation
# and resolves it to a real address (all four examples above -> 127.0.0.1) -
# a real bypass of the guard PM review on #56 asked for, found by a fresh
# review. Reject anything where every dot-separated label is purely numeric
# (decimal or 0x-hex) - the small risk of also rejecting a legitimate but
# all-numeric-label hostname is an acceptable trade for closing this off,
# since no real PrairieLearn deployment has ever used one.
_NUMERIC_LABEL = re.compile(r"^(0[xX][0-9a-fA-F]+|[0-9]+)$")


def _looks_like_numeric_ip(host):
    labels = host.split(".")
    return 1 <= len(labels) <= 4 and all(_NUMERIC_LABEL.match(label) for label in labels)


def resolve_campus(campus):
    """A known short key resolves from CAMPUSES; anything else is treated as
    a student-pasted PrairieLearn URL for an instance we don't have listed
    (any department can self-host one - see module docstring). Returns
    (campus_key, base_url); campus_key becomes both the saved-session
    filename (hub.site.state_path) and the item source, so for a custom URL
    it's `pl-<hostname>`, not the bare hostname or the full URL - the "pl-"
    prefix keeps it from ever colliding with another provider's own key
    (e.g. a pasted "https://canvas" used to overwrite Canvas's saved session
    and file its items under Canvas's source - PM review on #56 caught this
    live).

    A pasted URL that happens to match a *known* campus's base resolves to
    that campus's own key, not its own hostname - otherwise the same real
    instance could end up with two different source values (one from its
    quick-connect button, one from someone pasting its URL instead) and
    show up as two separate connections with duplicated items. Verified
    against a real account that hit exactly this after connecting the same
    UBC Okanagan instance both ways. The host is normalised (lowercased,
    default :443 port and any trailing dot stripped) before that comparison
    and before becoming a key, so "PrairieLearn.ok.ubc.ca", "...:443" and a
    trailing "." don't each create their own separate connection.

    Rejects anything that isn't a real https:// URL outright - this opens a
    real login browser window at whatever's returned, so a typo or a
    non-URL string must fail loudly here rather than reach Playwright.
    Also rejects a URL carrying userinfo (a classic look-alike-URL trick,
    e.g. "https://us.prairielearn.com@evil.example"), an IP literal, and
    "localhost" - none of those are a real PrairieLearn deployment, and
    letting one through would open the login browser at whatever host was
    actually meant (PM review on #56)."""
    if campus in CAMPUSES:
        return campus, CAMPUSES[campus]
    parsed = urlparse(campus)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"not a valid https:// PrairieLearn URL: {campus!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"URL must not contain a username/password: {campus!r}")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or _is_ip_literal(host) or _looks_like_numeric_ip(host):
        raise ValueError(f"not a real PrairieLearn hostname: {campus!r}")
    port = "" if parsed.port in (None, 443) else f":{parsed.port}"
    base = f"https://{host}{port}"
    for key, known_base in CAMPUSES.items():
        if known_base == base:
            return key, known_base
    return f"pl-{host}", base

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


def login(campus=DEFAULT_CAMPUS):
    """Open a visible browser; the student signs in (UBC CWL); we save the session."""
    key, base = resolve_campus(campus)
    site.login(key, base)


def _get_soup(req, path, base):
    r = req.get(f"{base}{path}")
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
                      credit_empty, campus_key, base):
    kind = KIND_FOR_GROUP.get(group.strip().lower(), "assignment")
    url = f"{base}{href}" if href else f"{base}/pl/course_instance/{ci_id}/assessments#{quote(title)}"
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=title,
        due=due_from_end_text(due_text) if due_text else None,
        url=url,
        source=campus_key,
        done=bool(done_from_score_text(score_text)) or done_from_credit_fields(credit_empty, score_text),
    )


def to_item(row, course_code, group, campus_key, base, ci_id):
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
        campus_key=campus_key, base=base,
    )


def parse_capture(capture):
    """Map selected assessment fields through the existing PrairieLearn rules."""
    # ponytail: PrairieLearn-only rule-6 DOM exception; use a student JSON API
    # if PrairieLearn offers one. This function never parses uploaded HTML.
    if not isinstance(capture, dict) or capture.get("source") != "prairielearn":
        raise ValueError("expected PrairieLearn capture")
    origin = capture.get("origin")
    if not isinstance(origin, str):
        raise ValueError("invalid PrairieLearn origin")
    try:
        campus_key, base = resolve_campus(origin)
    except ValueError:
        raise ValueError("invalid PrairieLearn origin") from None
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
                campus_key=campus_key, base=base,
            ))
    return courses, items


_CI_LINK = re.compile(r"^/pl/course_instance/(\d+)(?:/instructor)?/?$")


def _course_instances(req, base):
    """[(id, display title)] for every course on the student's home page.

    Matches both the student link (.../course_instance/<id>) and the
    instructor one (.../course_instance/<id>/instructor) - TAs/instructors
    used to see zero courses because only the student shape matched (#15).
    # ponytail: this still reads the student Assessments page for everyone
    (_assessments below), which may not be right for an instructor-only
    account - untested without a real TA login. Revisit if that's wrong."""
    soup, seen, out = _get_soup(req, "/", base), set(), []
    for a in soup.select("a[href^='/pl/course_instance/']"):
        m = _CI_LINK.match(a["href"])
        if not m or m[1] in seen:
            continue
        seen.add(m[1])
        out.append((m[1], a.get_text(strip=True)))
    return out


def _assessments(req, ci_id, course_code, campus_key, base):
    soup = _get_soup(req, f"/pl/course_instance/{ci_id}/assessments", base)
    items, group = [], ""
    for row in soup.select("table tbody tr"):
        heading = row.find("th")
        if heading:
            group = heading.get_text(strip=True)
        else:
            items.append(to_item(row, course_code, group, campus_key, base, ci_id))
    return items


def fetch(campus=DEFAULT_CAMPUS):
    """Return (courses, items) for every course on the student's PrairieLearn
    home page, for the given campus (a known CAMPUSES key, or a full
    https://... URL - see resolve_campus()). Opens a browser window to log
    in if there's no saved session for that campus."""
    key, base = resolve_campus(campus)
    return site.fetch_with_session(key, base, lambda req: _run(req, key, base))


def _run(req, campus_key, base):
    courses, items = [], []
    for ci_id, title in _course_instances(req, base):
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
        items += _assessments(req, ci_id, course.code, campus_key, base)
    return courses, items


if __name__ == "__main__":
    import sys

    from hub import db

    campus = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CAMPUS
    courses, items = fetch(campus)
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:10} {c.term:20} {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or datetime.max)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:10} {i.title}")
