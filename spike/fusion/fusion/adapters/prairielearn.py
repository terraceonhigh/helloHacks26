"""PrairieLearn adapter: what an enrolled student can read, as that student.

PrairieLearn gives students no JSON API (/pl/api/v1 needs a staff token), so:

1. GET /pl                         the student's home page. It embeds the
                                   "HomeCards" component props as JSON
                                   (studentCourses: course short_name/title,
                                   instance short_name/long_name). Fallback:
                                   the "Courses with student access" links.
2. GET /pl/course_instance/<id>/assessments
                                   one row per assessment: set badge ("Q1"),
                                   title, link, and an "Access details" popover
                                   listing the credit windows with full dates
                                   and the zone PL printed ("2026-10-02
                                   23:59:00 (PDT)").
3. GET <row link>, ONLY when the row already links to an
   /assessment_instance/ (the student has started it): the instance page, for
   links_out. An unstarted /assessment/<id>/ link is never fetched: for a
   Homework-type assessment PL creates an assessment instance on that GET (a
   write), and the list page does not say which type a row is (Exam-type rows,
   whose GET is a read-only "Start assessment" page, look identical).

PrairieLearn has no single due date. "due" here is the end of the 100 %-credit
window (the latest end among windows with credit >= 100). "opens" is the
earliest start among the windows the student is shown.
"""
import html as htmllib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from fusion.model import CourseObservation, Observation, Snapshot

NAME = "prairielearn"

# Zone abbreviations PrairieLearn prints (Intl timeZoneName "short"), to UTC offset hours.
# ponytail: a fixed table of North American + UTC abbreviations. Anything else
# is accepted only if the course instance's own display zone prints that same
# abbreviation at that instant; otherwise the date is dropped with a note.
# Upgrade path: widen the table as new schools show up.
ZONE_ABBR = {
    "UTC": 0, "GMT": 0,
    "PST": -8, "PDT": -7, "MST": -7, "MDT": -6, "CST": -6, "CDT": -5,
    "EST": -5, "EDT": -4, "AST": -4, "ADT": -3, "NST": -3.5, "NDT": -2.5,
    "AKST": -9, "AKDT": -8, "HST": -10,
}

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}(?::\d{2})?) \(([^)]+)\)")
_GMT_RE = re.compile(r"^(?:GMT|UTC)([+-])(\d{1,2})(?::?(\d{2}))?$")


def parse_pl_date(text: str, zone_hint: str | None = None) -> datetime | None:
    """'2026-10-02 23:59:00 (PDT)' -> tz-aware datetime, honouring the printed zone."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    day, clock, abbr = m.groups()
    fmt = "%Y-%m-%d %H:%M:%S" if clock.count(":") == 2 else "%Y-%m-%d %H:%M"
    naive = datetime.strptime(f"{day} {clock}", fmt)
    abbr = abbr.strip()
    if abbr in ZONE_ABBR:
        return naive.replace(tzinfo=timezone(timedelta(hours=ZONE_ABBR[abbr]), abbr))
    g = _GMT_RE.match(abbr)
    if g:
        sign, hh, mm = g.groups()
        off = timedelta(hours=int(hh), minutes=int(mm or 0)) * (1 if sign == "+" else -1)
        return naive.replace(tzinfo=timezone(off, abbr))
    if zone_hint:
        try:
            aware = naive.replace(tzinfo=ZoneInfo(zone_hint))
        except Exception:
            return None
        if aware.tzname() == abbr:
            return aware.replace(tzinfo=timezone(aware.utcoffset(), abbr))
    return None


def _kind(heading: str, badge: str) -> str:
    h = f"{heading} {badge}".lower()
    for words, kind in ((("exam", "midterm", "final", "test"), "exam"),
                        (("quiz",), "quiz"),
                        (("lab",), "lab"),
                        (("homework", "problem set", "hw", "ps"), "homework"),
                        (("worksheet", "assignment", "project"), "assignment")):
        if any(re.search(rf"\b{re.escape(w)}", h) for w in words):
            return kind
    return "assignment"


def _student_courses(home_html: str) -> list[dict]:
    """[{id, short_name, title, ci_short, ci_long, tz, text}] from the home page."""
    soup = BeautifulSoup(home_html, "html.parser")
    out = []
    tag = soup.find("script", attrs={"data-component": "HomeCards", "type": "application/json"})
    if tag and tag.string:
        try:
            props = json.loads(tag.string)
            props = props.get("json", props)
            for sc in props.get("studentCourses", []):
                c, ci = sc["course"], sc["course_instance"]
                out.append({"id": str(ci["id"]), "short_name": c["short_name"], "title": c["title"],
                            "ci_short": ci.get("short_name"), "ci_long": ci.get("long_name"),
                            "tz": ci.get("display_timezone") or c.get("display_timezone")})
        except (ValueError, KeyError, TypeError):
            out = []
    if out:
        return out
    # Fallback: "CPSC 121: Models of Computation, 2026 Winter Term 1" links.
    table = soup.find("table", attrs={"aria-label": "Courses with student access"})
    for a in (table.find_all("a", href=True) if table else []):
        m = re.search(r"/pl/course_instance/(\d+)/?$", a["href"])
        if not m:
            continue
        text = a.get_text("", strip=True)
        head, _, long = text.rpartition(",")
        short, _, title = head.partition(":")
        out.append({"id": m.group(1), "short_name": short.strip(), "title": title.strip(),
                    "ci_short": None, "ci_long": long.strip() or None, "tz": None})
    return out


def _windows(cell, tz_hint):
    """Credit windows from the row's 'Access details' popover: [(credit, start, end)]."""
    btn = cell.find(attrs={"data-bs-title": "Access details"})
    if not btn:
        return None
    inner = BeautifulSoup(htmllib.unescape(btn.get("data-bs-content", "")), "html.parser")
    rows = []
    for tr in inner.find_all("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) != 3:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", tds[0])
        rows.append((float(m.group(1)) if m else None,
                     parse_pl_date(tds[1], tz_hint), parse_pl_date(tds[2], tz_hint), tds))
    return rows


_DEFAULT_PORT = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None] | None:
    """(scheme, lowercased host, effective port), or None if the URL can't be parsed."""
    try:
        p = urlparse(url)
        return p.scheme, (p.hostname or "").lower(), p.port or _DEFAULT_PORT.get(p.scheme)
    except ValueError:                    # bad port / broken IPv6 host in an instructor's href
        return None


def _external_links(page_html: str, base: str) -> tuple[str, ...]:
    """Links in <main> to another host OR another platform on the same host (a different port)."""
    soup = BeautifulSoup(page_html, "html.parser")
    main = soup.find("main") or soup
    own = _origin(base)
    own_hp = own[1:] if own else None
    seen = []
    for a in main.find_all("a", href=True):
        try:
            href = urljoin(base, a["href"])
        except ValueError:
            continue
        o = _origin(href)
        if o and o[0] in ("http", "https") and o[1] and o[1:] != own_hp and href not in seen:
            seen.append(href)
    return tuple(seen)


def parse_assessments(page_html: str, base: str, ci_id: str, tz_hint: str | None, notes: list):
    """Rows of one course instance's assessments page -> [(Observation fields dict, link_is_instance)]."""
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.find("table", attrs={"aria-label": "Assessments"})
    if table is None:
        raise ValueError(f"course instance {ci_id}: no Assessments table on the page")
    list_url = f"{base}/pl/course_instance/{ci_id}/assessments"
    out = []
    for tbody in table.find_all("tbody"):
        heading_el = tbody.find(attrs={"data-testid": "assessment-group-heading"})
        heading = heading_el.get_text(" ", strip=True) if heading_el else ""
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            badge_el = tds[0].find(attrs={"data-testid": "assessment-set-badge"})
            badge = badge_el.get_text("", strip=True) if badge_el else tds[0].get_text("", strip=True)
            if "#" in badge:
                # ponytail: rows "Q1#2" are extra instances of a multi-instance
                # assessment; the header row "Q1" is the item. Upgrade path:
                # surface per-instance state if fusion ever needs it.
                continue
            a = tds[1].find("a", href=True)
            title = (a or tds[1]).get_text(" ", strip=True)
            windows = _windows(tds[2], tz_hint)
            summary = " ".join(tds[2].get_text(" ", strip=True).split())
            due = opens = None
            if windows is None:
                notes.append(f"{badge} {title!r}: no Access details popover (summary {summary!r}); no dates")
            else:
                for credit, start, end, raw in windows:
                    for label, val, txt in (("start", start, raw[1]), ("end", end, raw[2])):
                        if val is None and _DATE_RE.search(txt):
                            notes.append(f"{badge} {title!r}: unrecognised zone in {label} {txt!r}; dropped")
                full = [w for w in windows if w[0] is not None and w[0] >= 100 and w[2] is not None]
                if full:
                    due = max(w[2] for w in full)
                else:
                    pos = [w for w in windows if w[0] and w[2] is not None]
                    if pos:
                        best = max(w[0] for w in pos)
                        due = max(w[2] for w in pos if w[0] == best)
                        notes.append(f"{badge} {title!r}: no 100% window; due is the end of the {best:g}% window")
                starts = [w[1] for w in windows if w[1] is not None and (w[0] is None or w[0] > 0)]
                opens = min(starts) if starts else None
            if a is not None:
                url = urljoin(base + "/", a["href"])
            else:
                # Not startable yet (e.g. before it opens): PL renders the title
                # without a link and never shows the student the assessment id.
                # ponytail: fall back to the instance's assessments page, with the
                # row label as a fragment so the url stays this item's own (a bare
                # list url shared by every unopened row, or linked generically from
                # another platform, must never be fusion link evidence). Upgrade
                # path: once it opens, the next fetch carries the deep link.
                url = f"{list_url}#{badge}"
                notes.append(f"{badge} {title!r}: no link for the student yet ({summary!r}); url is the assessments page")
            score = tds[3].get_text(" ", strip=True) if len(tds) > 3 else ""
            out.append(dict(
                source=NAME,
                # The row label (set abbreviation + number) is PL's own stable
                # name for the assessment within the instance, and, unlike the
                # link, it survives the student starting the assessment and a
                # not-yet-linked assessment opening.
                source_id=f"{ci_id}:{badge}",
                course_source_id=ci_id,
                kind=_kind(heading, badge),
                title=title,
                due=due,
                opens=opens,
                url=url,
                # ponytail: done stays None; PL's list shows only a score, and a
                # started homework isn't "submitted". Upgrade path: map score
                # 100% or a closed instance to done=True.
                done=None,
                excerpt=f"[{heading}] {badge}: {summary} | {score}"[:280],
            ))
    return out


def fetch(session: requests.Session, base: str) -> Snapshot:
    base = base.rstrip("/")
    notes: list[str] = []
    r = session.get(f"{base}/pl", timeout=30)
    r.raise_for_status()
    courses_raw = _student_courses(r.text)
    if not courses_raw:
        notes.append("no courses with student access on /pl")
    courses, items = [], []
    for c in courses_raw:
        ci = c["id"]
        label = f"{c['short_name']}, {c['ci_short']}" if c["ci_short"] else c["short_name"]
        title = f"{c['short_name']}: {c['title']}" + (f", {c['ci_long']}" if c["ci_long"] else "")
        courses.append(CourseObservation(source=NAME, source_id=ci, label=label, title=title,
                                         term_hint=c["ci_long"], url=f"{base}/pl/course_instance/{ci}"))
        page = session.get(f"{base}/pl/course_instance/{ci}/assessments", timeout=30)
        page.raise_for_status()
        for fields in parse_assessments(page.text, base, ci, c["tz"], notes):
            links_out = ()
            # ponytail: links_out only for started assessments. An unstarted Exam's
            # /assessment/<id>/ start page is a safe read and may carry cross-platform
            # links in its text, but the list page can't tell it from a Homework, whose
            # GET is a write. Upgrade path: learn the type (staff API, or a type marker
            # if PL adds one to the student list) and GET only Exam-type start pages.
            if "/assessment_instance/" in fields["url"]:
                inst = session.get(fields["url"], timeout=30)   # already started: a plain read
                if inst.ok:
                    links_out = _external_links(inst.text, base)
                else:
                    notes.append(f"{fields['source_id']}: instance page HTTP {inst.status_code}")
            items.append(Observation(**fields, links_out=links_out))
    return Snapshot(source=NAME, base=base, fetched_at=datetime.now(timezone.utc),
                    courses=tuple(courses), items=tuple(items), notes=tuple(notes))
