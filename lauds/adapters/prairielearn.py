"""PrairieLearn adapter: browser-session login (lauds.session), then scrape
each enrolled course's Assessments page for tasks/deadlines. PrairieLearn has
no student-facing API (docs/api-standards.md in the oracle repo), so this
reads the same HTML a student sees - same reasoning as Canvas's browser-login
path reading its JSON.

PrairieLearn is open-source and self-hostable by anyone, not one deployment
per school - a real student's assessments turned out to live on their
school's *own* PrairieLearn instance, not the shared PrairieLearn SaaS their
other courses used, and a second, independent self-hosted instance turned up
in the same search - so a hardcoded list of campuses can never be complete.
`campus` accepts either a known short key (CAMPUSES) or a student-pasted
"https://..." URL directly - see `resolve_campus()`. Same PrairieLearn
codebase either way, so the same scraping logic works against any of them -
only the base URL and the saved session differ. Each campus gets its own
saved session and its own `source` value, so items from one never collide
with another's.

Verified against a real course on the shared SaaS instance (main's own
docstring: CPSC 317, 2026 Winter Term 1) and against a disposable self-hosted
instance on humboldt (tests/oracle/prairielearn/live_selfhost.json).
# ponytail: a student-pasted custom-domain instance hasn't itself been
# verified against a real login - assumed identical markup since it's the
# same open-source codebase. Flag here if a real login shows different HTML.

Two real limitations of the source data, not this code's doing:
- PrairieLearn has no single "due date" - each assessment has a multi-tier
  credit schedule (100% until X, 70% until Y, ...). `due` is the end of the
  100%-credit tier, the same meaning as "due date" for a student.
- An assessment PrairieLearn hasn't opened yet shows only an "Available
  <time>, <weekday>, <month> <day>" notice (no year, no tier table) - not
  enough to build an exact datetime, so those come back with `due=None`
  rather than a guess.
"""
import ipaddress
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from lauds import session
from lauds.models import Bundle, Course, Item, category_for

NAME = "prairielearn"
DESCRIPTION = "PrairieLearn: assessments (any campus, incl. self-hosted)"

CAMPUSES = {
    "prairielearn": "https://us.prairielearn.com",
    "prairielearn_ok": "https://prairielearn.ok.ubc.ca",
}
DEFAULT_CAMPUS = "prairielearn"

# --- resolve_campus: multi-campus + its SSRF hardening ----------------------
#
# ipaddress.ip_address() only recognises the canonical dotted-quad/full-IPv6
# forms - it rejects "127.1", "2130706433", "0x7f000001" and "017700000001"
# as not-an-IP, which would let all four of those through as "ordinary
# hostnames". A browser's URL parser (what a real login actually navigates
# with) accepts every one of those as an alternate IPv4 notation and resolves
# it to a real address (all four examples above -> 127.0.0.1): a genuine
# bypass of an IP-literal guard, closed by rejecting anything where every
# dot-separated label is purely numeric (decimal or 0x-hex) - the small risk
# of also rejecting a legitimate but all-numeric-label hostname is an
# acceptable trade, since no real PrairieLearn deployment has ever used one.
_NUMERIC_LABEL = re.compile(r"^(0[xX][0-9a-fA-F]+|[0-9]+)$")


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _is_numeric_ipv4_lookalike(host: str) -> bool:
    labels = host.split(".")
    return 1 <= len(labels) <= 4 and all(_NUMERIC_LABEL.match(label) for label in labels)


def resolve_campus(campus: str) -> tuple[str, str]:
    """A known short key resolves from CAMPUSES; anything else is treated as
    a student-pasted PrairieLearn URL for an instance we don't have listed
    (any department can self-host one - see module docstring). Returns
    (campus_key, base_url); campus_key becomes both the saved-session
    filename and the item source, so for a custom URL it's `pl-<hostname>`,
    not the bare hostname or the full URL - the "pl-" prefix keeps it from
    ever colliding with another provider's own key (a pasted
    "https://canvas" must never overwrite Canvas's saved session or file
    its items under Canvas's source).

    A pasted URL that happens to match a *known* campus's base resolves to
    that campus's own key, not its own hostname - otherwise the same real
    instance could end up with two different source values (one from its
    quick-connect button, one from someone pasting its URL instead) and show
    up as two separate connections with duplicated items. The host is
    normalised (lowercased, default :443 port and any trailing dot stripped)
    before that comparison and before becoming a key, so case, an explicit
    default port, and a trailing dot don't each create their own connection.

    Rejects anything that isn't a real https:// URL outright - this opens a
    real login browser window at whatever's returned, so a typo or a non-URL
    string must fail loudly here rather than reach the browser. Also rejects
    a URL carrying userinfo (a look-alike-URL trick, e.g.
    "https://us.prairielearn.com@evil.example"), an IP literal, "localhost",
    and every legacy/alternate IPv4 notation a browser would still resolve -
    none of those is a real PrairieLearn deployment, and letting one through
    would open the login browser at whatever host was actually meant.
    """
    if campus in CAMPUSES:
        return campus, CAMPUSES[campus]
    parsed = urlparse(campus)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"not a valid https:// PrairieLearn URL: {campus!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"URL must not contain a username/password: {campus!r}")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or _is_ip_literal(host) or _is_numeric_ipv4_lookalike(host):
        raise ValueError(f"not a real PrairieLearn hostname: {campus!r}")
    port = "" if parsed.port in (None, 443) else f":{parsed.port}"
    base = f"https://{host}{port}"
    for key, known_base in CAMPUSES.items():
        if known_base == base:
            return key, known_base
    return f"pl-{host}", base


# UBC courses only ever show Pacific time. Fixed offsets, not zoneinfo/pytz:
# good enough while every course seen is UBC; add zones if that changes.
# "MST" included for BC's 2027-01-06 permanent-DST tzdata change: once BC
# stops changing clocks, tzdata names the resulting fixed UTC-7 offset "MST"
# (it coincides with Mountain Standard Time), even though it's still what
# PrairieLearn shows as "Vancouver time".
TZ_OFFSET = {"PST": -8, "PDT": -7, "MST": -7}

# PrairieLearn groups assessments under headings an instructor names freely
# ("Programming Assignments", "Tutorial", ...); these are the ones known to
# mean something other than a plain task. Unlisted -> "assignment".
KIND_FOR_GROUP = {
    "practice for quizzes": "quiz",
    "quizzes": "quiz",
    "formal quizzes": "exam",
    "formal quizzes (repeated for practice)": "exam",
    "exams": "exam",
}

COURSE_TITLE = re.compile(r"([A-Z]+ ?\d+\w*):\s*(.+),\s*(\d{4} \w+ Term \d+)")
_CI_LINK = re.compile(r"^/pl/course_instance/(\d+)(?:/instructor)?/?$")
_SCORE = re.compile(r"([\d.]+)\s*%")


def login(campus: str = DEFAULT_CAMPUS) -> None:
    """Open a visible browser; the student signs in (their school's SSO); we
    save the session."""
    key, base = resolve_campus(campus)
    session.login(key, base)


def to_course(ci_id: str, title: str) -> Course:
    m = COURSE_TITLE.match(title)
    if not m:  # ponytail: title format changed/unexpected - keep the raw text rather than crash
        return Course(code=title, section="", term="", title=title)
    code, name, term = m.groups()
    return Course(code=code, section="", term=term, title=name)


def due_from_end_text(end: str) -> datetime | None:
    """Parse a 100%-credit tier's end text ("2026-09-27 23:59:59 (PDT)") from
    either input path (a scraped popover or an extension capture)."""
    m = re.match(r"(.+) \(([A-Z]+)\)$", end)
    if not m:
        return None
    dt_str, tz = m.groups()
    if tz not in TZ_OFFSET:
        # Silently treating an unrecognised abbreviation as UTC would be a
        # 7h-off bug waiting to happen - fail loud instead.
        raise ValueError(f"unrecognized PrairieLearn timezone abbreviation: {tz!r}")
    return datetime.fromisoformat(dt_str).replace(tzinfo=timezone(timedelta(hours=TZ_OFFSET[tz])))


def due_from_popover(popover_html: str | None) -> datetime | None:
    """The access-details popover's first row (100% credit) -> its end time.
    None if there's no popover yet (assessment not open, see module
    docstring)."""
    if not popover_html:
        return None
    rows = BeautifulSoup(popover_html, "html.parser").select("tr")[1:]  # skip Credit/Start/End header
    if not rows:
        return None
    end = rows[0].select("td")[2].get_text(strip=True)  # "2026-09-27 23:59:59 (PDT)" or "—"
    return due_from_end_text(end)


def done_from_score_text(score_text: str) -> bool:
    m = _SCORE.search(score_text)
    return m is not None and float(m.group(1)) >= 100


def done_from_score(cells) -> bool | None:
    """The 4th column shows a percentage once attempted, or a status like
    "Not started"/"Not yet released" otherwise. A 100% score is one signal
    for "nothing left to do here" - a lower score is still improvable until
    the assessment closes (see `done_from_credit_fields` for that case)."""
    if len(cells) < 4:
        return None
    return done_from_score_text(cells[3].get_text(strip=True))


def done_from_credit_fields(credit_empty: bool, score_text: str) -> bool:
    """Once an assessment's whole credit schedule has expired, the Available
    Credit column shows nothing at all (no popover, no "Available <time>"
    notice) - since nothing left could still change the score. A closed
    assessment can show this with a score well under 100%, which
    `done_from_score_text` alone would miss.

    An empty credit cell alone isn't enough, though: PrairieLearn also shows
    an empty cell for an assessment that still accepts 0%-credit "practice"
    submissions after its last deadline - that's not finished, just not worth
    more points anymore. Require a nonzero score too, so a never-attempted
    assessment in that state stays visible instead of silently
    disappearing."""
    if not credit_empty:
        return False
    m = _SCORE.search(score_text)
    return m is not None and float(m.group(1)) > 0


def done_from_credit(cells) -> bool:
    if len(cells) < 4:
        return False
    credit_cell = cells[2]
    credit_empty = credit_cell.find("button") is None and credit_cell.get_text(strip=True) == ""
    return done_from_credit_fields(credit_empty, cells[3].get_text(strip=True))


def _build_item(*, title, group, ci_id, course_code, href, due_text, score_text,
                 credit_empty, campus_key, base) -> Item:
    """The one place row fields (however they were obtained - scraped table
    cells, or an extension capture) become an Item. Shared by `parse_row`
    and `parse_capture` so the mapping rule lives in exactly one spot."""
    kind = KIND_FOR_GROUP.get(group.strip().lower(), "assignment")
    # An assessment PrairieLearn hasn't opened yet has no link (module
    # docstring), so url="" used to be its identity - every unreleased
    # assessment in every course would then collapse onto one row. Fall back
    # to the assessments page plus the title: unique enough within a course
    # and stable across re-fetches until the assessment actually opens.
    url = f"{base}{href}" if href else f"{base}/pl/course_instance/{ci_id}/assessments#{quote(title)}"
    done = done_from_score_text(score_text) or done_from_credit_fields(credit_empty, score_text)
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=title,
        due=due_from_end_text(due_text) if due_text else None,
        url=url,
        source=campus_key,
        done=done,
    )


def parse_row(row, *, course_code: str, group: str, campus_key: str, base: str, ci_id: str) -> Item:
    """One `<tr>` from a course's Assessments table -> an Item."""
    cells = row.select("td")
    link = cells[1].find("a")
    popover = cells[2].find("button")
    title = cells[1].get_text(strip=True)
    due_text = ""
    if popover:
        rows = BeautifulSoup(popover["data-bs-content"], "html.parser").select("tr")[1:]
        if rows:
            due_text = rows[0].select("td")[2].get_text(strip=True)
    return _build_item(
        title=title, group=group, ci_id=ci_id, course_code=course_code,
        href=link["href"] if link else "", due_text=due_text,
        score_text=cells[3].get_text(strip=True) if len(cells) > 3 else "",
        credit_empty=(cells[2].find("button") is None and cells[2].get_text(strip=True) == ""),
        campus_key=campus_key, base=base,
    )


def parse_assessments_page(html: str, *, course_code: str, campus_key: str, base: str, ci_id: str) -> list[Item]:
    """The full Assessments page (raw HTML) -> every Item on it, honouring
    the group headings ("Programming Assignments", "Quizzes", ...) each row
    falls under."""
    soup = BeautifulSoup(html, "html.parser")
    items, group = [], ""
    for row in soup.select("table tbody tr"):
        heading = row.find("th")
        if heading:
            group = heading.get_text(strip=True)
        else:
            items.append(parse_row(row, course_code=course_code, group=group,
                                   campus_key=campus_key, base=base, ci_id=ci_id))
    return items


def parse_capture(capture: dict) -> tuple[list[Course], list[Item]]:
    """Map an extension-captured PrairieLearn payload through the same
    mapping rules as a server-side scrape.
    # ponytail: PrairieLearn-only rule-6 DOM exception; use a student JSON
    # API if PrairieLearn ever offers one. This function never parses
    # uploaded HTML - only a capture's own already-extracted text fields."""
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
            or any(not isinstance(c, dict) for c in raw_courses)):
        raise ValueError("invalid PrairieLearn courses")
    courses, items = [], []
    for raw in raw_courses:
        ci_id, title, assessments = raw.get("ci_id"), raw.get("title"), raw.get("assessments")
        if (not isinstance(ci_id, str) or not ci_id.isdecimal()
                or not isinstance(title, str) or not title
                or not isinstance(assessments, list) or len(assessments) > 300):
            raise ValueError("invalid PrairieLearn course")
        if not COURSE_TITLE.match(title):
            continue  # same example-course filter as the page scrape
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
            if (any(not isinstance(row.get(f, ""), str) for f in fields) or not row.get("title")):
                raise ValueError("invalid PrairieLearn assessment fields")
            if not isinstance(row.get("credit_empty", False), bool):
                raise ValueError("invalid PrairieLearn credit status")
            items.append(_build_item(
                title=row.get("title", ""), group=row.get("group", ""),
                ci_id=ci_id, course_code=course.code, href=href,
                due_text=row.get("due_text", ""), score_text=row.get("score_text", ""),
                credit_empty=row.get("credit_empty", False),
                campus_key=campus_key, base=base,
            ))
    return courses, items


def _get(req, path: str, base: str):
    r = req.get(f"{base}{path}")
    if r.status == 401:
        raise session.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{path} -> {r.status}")
    return r.text()


def _course_instances(req, base: str) -> list[tuple[str, str]]:
    """[(id, display title)] for every course on the student's home page.

    Matches both the student link (.../course_instance/<id>) and the
    instructor one (.../course_instance/<id>/instructor) - a TA/instructor
    account would otherwise see zero courses.
    # ponytail: this still reads the student Assessments page for everyone
    # below, which may not be right for an instructor-only account -
    # untested without a real TA login."""
    soup = BeautifulSoup(_get(req, "/", base), "html.parser")
    seen, out = set(), []
    for a in soup.select("a[href^='/pl/course_instance/']"):
        m = _CI_LINK.match(a["href"])
        if not m or m[1] in seen:
            continue
        seen.add(m[1])
        out.append((m[1], a.get_text(strip=True)))
    return out


def _run(req, campus_key: str, base: str) -> tuple[list[Course], list[Item]]:
    courses, items = [], []
    for ci_id, title in _course_instances(req, base):
        if not COURSE_TITLE.match(title):
            # ponytail: skip instances that don't look like a real course
            # code - this also filters out PrairieLearn's own built-in
            # example course, which the wider instructor-link matching above
            # would otherwise surface as a phantom course. Upgrade: ask
            # PrairieLearn for real course metadata if that's ever exposed,
            # instead of sniffing the title.
            continue
        course = to_course(ci_id, title)
        courses.append(course)
        html = _get(req, f"/pl/course_instance/{ci_id}/assessments", base)
        items += parse_assessments_page(html, course_code=course.code, campus_key=campus_key,
                                        base=base, ci_id=ci_id)
    return courses, items


def fetch(campus: str = DEFAULT_CAMPUS) -> Bundle:
    """Every course and assessment on the student's PrairieLearn home page,
    for the given campus (a known CAMPUSES key, or a full https://... URL -
    see `resolve_campus()`). Opens a browser window to log in if there's no
    saved session for that campus."""
    key, base = resolve_campus(campus)
    courses, items = session.fetch_with_session(key, base, lambda req: _run(req, key, base))
    return Bundle(courses=courses, items=items)
