"""WeBWorK adapter: the student's set list and each set's own page, as HTML.

WeBWorK 2.x has no JSON API a student session can call (instructor_rpc and
render_rpc are instructor/render tools), so this parses the pages the student
sees:

  <course>/                 set list: one <li data-set-status=...> per visible set
  <course>/<set_id>         the set's own page: status line + "Set Info" header

What WeBWorK prints depends on the set's state (verified on WeBWorK 2.21):

  state      set list line                                set page status line
  open       "Open. Due <date>."                          "Set closes on <date>."
  not-open   "Will open on <date>."                       "Set opens on <date>."
  past-due   "Answers available for review[ on <date>]."  "Set is closed."

So for past-due and not-yet-open sets the ONLY student-visible due date is the
set header ("Set Info"). WeBWorK's default header prints
"This assignment will close on <date>." (from $formattedDueDate). An
instructor can replace that header; then those sets come back with due=None
and a note, never a guessed date.

Dates look like "September 29, 2026, 11:59:00 PM PDT" (older releases: "... 2026
at 11:59pm PDT"). The zone is whatever WeBWorK's own Perl tz database said for
that instant. We map the printed abbreviation or offset to a fixed UTC offset
and never re-derive it from a zone name: WeBWorK printed "PST" for Jan 2027 in
America/Vancouver while newer OS tzdata puts BC on permanent UTC-7 from
2026-11-01. The instant WeBWorK prints is the one the student is held to.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from fusion.model import CourseObservation, Observation, Snapshot

NAME = "webwork"

# ponytail: only North American + UTC abbreviations. Abbreviations are ambiguous
# worldwide (CST, IST, BST...), so anything else is refused (due=None + a note),
# never guessed. Upgrade: add unambiguous ones here, or read a numeric offset if
# the site sets a date format with %z.
ZONE_OFFSETS = {
    "UTC": 0, "GMT": 0, "Z": 0,
    "NST": -3.5, "NDT": -2.5,
    "AST": -4, "ADT": -3,
    "EST": -5, "EDT": -4,
    "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6,
    "PST": -8, "PDT": -7,
    "AKST": -9, "AKDT": -8,
    "HST": -10,
}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}

# "September 29, 2026, 11:59:00 PM PDT" | "September 29, 2026 at 11:59pm PDT" | "... -0700"
# ponytail: English month names only (datetime_format_long in the 'en' locale).
# Upgrade: per-locale month tables, keyed off <html lang>.
DATE_RE = re.compile(
    r"(?P<mon>[A-Za-z]+)\.? (?P<day>\d{1,2}), (?P<year>\d{4})(?:,| at) "
    r"(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))? ?(?P<ampm>[AaPp]\.?[Mm]\.?)? "
    r"(?P<zone>[A-Z]{1,5}|[+-]\d{2}:?\d{2}|(?:UTC|GMT)[+-]\d{1,2}(?::?\d{2})?)\b"
)


class ZoneUnknown(ValueError):
    pass


def _tz(zone: str) -> timezone:
    if zone in ZONE_OFFSETS:
        return timezone(timedelta(hours=ZONE_OFFSETS[zone]), zone)
    m = re.fullmatch(r"(?:UTC|GMT)?([+-])(\d{1,2}):?(\d{2})?", zone)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
    raise ZoneUnknown(f"unrecognised time zone {zone!r}")


def parse_date(text: str) -> datetime | None:
    """First WeBWorK-printed date in text, tz-aware at the printed offset. None if absent."""
    m = DATE_RE.search(text)
    if not m:
        return None
    mon = MONTHS.get(m["mon"].lower()) or next(
        (v for k, v in MONTHS.items() if k.startswith(m["mon"].lower()[:3])), None)
    if mon is None:
        return None
    h = int(m["h"])
    if m["ampm"]:
        pm = m["ampm"][0].lower() == "p"
        h = (h % 12) + (12 if pm else 0)
    return datetime(int(m["year"]), mon, int(m["day"]), h, int(m["mi"]), int(m["s"] or 0),
                    tzinfo=_tz(m["zone"]))


def _text(el) -> str:
    return " ".join(el.get_text(" ").split()) if el is not None else ""


def _clean_url(url: str) -> str:
    """Drop the query (effectiveUser=... is per-viewer, not the item) and fragment."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def _links_out(el, page_url: str) -> list[str]:
    """Absolute hrefs in el that point at a different host than WeBWorK."""
    if el is None:
        return []
    host = urlsplit(page_url).netloc.lower()
    out = []

    def keep(u):
        try:
            p = urlsplit(u)
        except ValueError:            # broken IPv6 host in a typo'd link: not a usable link
            return
        if p.scheme in ("http", "https") and p.netloc.lower() != host and u not in out:
            out.append(u)

    for a in el.find_all("a", href=True):
        try:
            keep(urljoin(page_url, a["href"]))
        except ValueError:
            continue
    # Links written as plain text in a description (no <a>).
    for u in re.findall(r"https?://[^\s<>\"')]+", el.get_text(" ")):
        keep(u.rstrip(".,;"))
    return out


def _date_or_note(text: str, what: str, notes: list[str]) -> datetime | None:
    try:
        return parse_date(text)
    except ZoneUnknown as e:
        notes.append(f"{what}: {e}; date dropped rather than guessed")
        return None


def split_base(base: str) -> tuple[str, str | None]:
    """(server root with /webwork2, course id or None)."""
    base = base.rstrip("/")
    if "/webwork2" not in base:
        return base + "/webwork2", None
    root, rest = base.split("/webwork2", 1)
    course = rest.strip("/").split("/")[0] or None
    return root + "/webwork2", course


def list_courses(session, ww_root: str) -> list[str]:
    """Course ids on the site index. Only those the session is logged in to are kept later."""
    r = session.get(ww_root + "/", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    ids = []
    for a in soup.find_all("a", href=True):
        path = urlsplit(urljoin(r.url, a["href"])).path.rstrip("/")
        m = re.fullmatch(r".*/webwork2/([^/?#]+)", path)
        if m and m.group(1) != "admin" and m.group(1) not in ids:
            ids.append(unquote(m.group(1)))
    return ids


def parse_set_list(html: str, course_url: str) -> tuple[str, list[dict]]:
    """(course title, [{set_id, title, status, type, line, description_el, url}]) from the course page."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(id="login_form") is not None:
        raise PermissionError("not logged in to this WeBWorK course")
    crumbs = soup.select("ol.breadcrumb li")
    course_title = _text(crumbs[1]) if len(crumbs) > 1 else ""
    sets = []
    for li in soup.select("li[data-set-status]"):
        a = li.select_one("a.fw-bold[href]")
        if a is None:
            continue
        url = _clean_url(urljoin(course_url + "/", a["href"]))
        set_id = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
        lines = li.select("div.font-sm")
        tip = li.select_one("[data-bs-title].set-id-tooltip[role=button]")
        sets.append({
            "set_id": set_id,
            "title": _text(a),
            "status": li.get("data-set-status"),
            "type": li.get("data-set-type"),
            "line": _text(lines[0]) if lines else "",
            "description": tip.get("data-bs-title", "") if tip is not None else "",
            "url": url,
        })
    return course_title, sets


def parse_set_page(html: str) -> dict:
    """Status line, Set Info header text/element, description element, problem statuses."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.find(id="login_form") is not None:
        raise PermissionError("not logged in to this WeBWorK course")
    body = soup.select_one("div.body") or soup
    status = body.select_one("div.alert-info")
    desc = body.select_one("div.alert-secondary")
    # The rendered set header lives in the right-hand info panel (the left
    # sidebar has another .info-box listing the sets: not this one).
    info = soup.select_one("#info-panel-right .info-box") or soup.select_one("#info-panel-right")
    statuses = []
    table = soup.select_one("table.problem_set_table") or soup.select_one("table")
    if table is not None:
        head = [_text(th).lower() for th in table.select("thead th")] or \
               [_text(c).lower() for c in (table.find("tr") or []).find_all(["th", "td"])]
        col = next((i for i, h in enumerate(head) if h.startswith("status")), None)
        if col is not None:
            for tr in table.select("tbody tr") or table.find_all("tr")[1:]:
                cells = tr.find_all(["td", "th"])
                if len(cells) > col:
                    statuses.append(_text(cells[col]))
    return {"status_line": _text(status), "info_el": info, "info_text": _text(info),
            "desc_el": desc, "problem_statuses": statuses}


def _done(statuses: list[str]) -> bool | None:
    if not statuses:
        return None
    pct = []
    for s in statuses:
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        if not m:
            return None
        pct.append(float(m.group(1)))
    return all(p >= 100 for p in pct)


def build_observation(course_id: str, s: dict, page: dict, notes: list[str]) -> Observation:
    sid = f"{course_id}/{s['set_id']}"
    line, status_line, info = s["line"], page["status_line"], page["info_text"]
    due = opens = None
    due_from = None

    if s["status"] == "open":
        # "Open. Due X." (list) / "Set closes on X." (page): app-generated, trusted first.
        # ponytail: with reduced scoring on, "Open. Due X" is the reduced-scoring
        # start and the real close is in "Afterward reduced credit ... until Y"; we
        # take the page's "Set closes on" (the close) first for that reason.
        if status_line.lower().startswith("set closes on"):
            due, due_from = _date_or_note(status_line, sid, notes), "set page status"
        if due is None and line.lower().startswith("open. due"):
            due, due_from = _date_or_note(line, sid, notes), "set list"
    elif s["status"] == "not-open":
        opens = _date_or_note(line, sid, notes) or _date_or_note(status_line, sid, notes)
    if due is None and re.search(r"\bclose[sd]?\b", info, re.I):
        # Instructor-editable set header; WeBWorK's default prints the due date here.
        due, due_from = _date_or_note(info, sid, notes), "set header"
    if due is None:
        notes.append(f"{sid}: no due date visible to the student (status {s['status']})")

    kind = "quiz" if s["type"] == "test" else "homework"
    links = []
    for el in (page["desc_el"], page["info_el"]):
        for u in _links_out(el, s["url"]):
            if u not in links:
                links.append(u)
    if s["description"]:
        for u in _links_out(BeautifulSoup(s["description"], "html.parser"), s["url"]):
            if u not in links:
                links.append(u)
    excerpt = " | ".join(x for x in (line, status_line, info) if x)
    if due_from:
        excerpt = f"[due from {due_from}] " + excerpt
    return Observation(
        source=NAME, source_id=sid, course_source_id=course_id, kind=kind, title=s["title"],
        due=due, opens=opens, url=s["url"], submit_url=None, links_out=tuple(links),
        done=_done(page["problem_statuses"]), weight=None, excerpt=excerpt[:280] or None,
    )


def fetch_course(session, ww_root: str, course_id: str, notes: list[str]):
    course_url = f"{ww_root}/{course_id}"
    r = session.get(course_url + "/", timeout=30)
    r.raise_for_status()
    title, sets = parse_set_list(r.text, course_url)
    course = CourseObservation(source=NAME, source_id=course_id, label=course_id,
                               title=title or course_id.replace("_", " "), term_hint=None, url=course_url)
    items = []
    for s in sets:
        p = session.get(s["url"], timeout=30)
        p.raise_for_status()
        items.append(build_observation(course_id, s, parse_set_page(p.text), notes))
    return course, items


def fetch(session, base: str) -> Snapshot:
    """base: a course URL (http://host/webwork2/<course>) or the server root.

    From the server root, every course on the site index that this session is
    logged in to is read (WeBWorK sessions are per course: one cookie each).
    """
    ww_root, course = split_base(base)
    notes: list[str] = []
    course_ids = [course] if course else list_courses(session, ww_root)
    courses, items = [], []
    for cid in course_ids:
        try:
            c, its = fetch_course(session, ww_root, cid, notes)
        except PermissionError:
            if course:
                raise
            continue  # listed on the site but this session isn't logged in to it
        courses.append(c)
        items.extend(its)
    if not courses:
        raise PermissionError(f"session is not logged in to any WeBWorK course at {base}")
    return Snapshot(source=NAME, base=base, fetched_at=datetime.now(timezone.utc),
                    courses=tuple(courses), items=tuple(items), notes=tuple(notes))
