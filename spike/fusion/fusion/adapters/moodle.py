"""Moodle adapter: what an enrolled student can read, as that student.

Behind SSO the student only has a browser session (MoodleSession cookie), not
a web-service token. So this adapter calls what Moodle's own UI calls with
that session: the AJAX endpoint /lib/ajax/service.php?sesskey=..., which only
serves functions flagged 'ajax' => true. Verified on Moodle 4.5 that these are
AJAX-enabled and used here:

1. GET /my/                                        any logged-in page, for the sesskey (M.cfg)
2. core_course_get_enrolled_courses_by_timeline_classification
                                                   the student's courses (shortname, fullname, viewurl,
                                                   startdate/enddate)
3. core_courseformat_get_state(courseid)           every course module the student sees (id, name,
                                                   module, url, uservisible): includes undated ones
4. core_calendar_get_calendar_monthly_view         per month over the courses' date range: course events
                                                   (Midterm...) and activity events (assign "due",
                                                   quiz "open"/"close") as epoch timestamps
5. GET /mod/assign/view.php?id=N, /mod/page/view.php?id=N
                                                   the item's own page, for the description (links_out),
                                                   submission state (done) and the submit button

NOT AJAX-enabled (so a browser session can't call them): mod_assign_get_assignments,
mod_assign_get_submission_status, core_course_get_contents, core_calendar_get_calendar_events,
core_enrol_get_users_courses, mod_page_get_pages_by_courses. Hence step 5 is HTML.

Dates: Moodle stores and serves instants as Unix epochs, so the instant is
exact. The offset attached is the one the server's own calendar used for that
day (day.timestamp is the user's local midnight), not one re-derived from a
zone name.
"""
import html as htmllib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from fusion.model import CourseObservation, Observation, Snapshot

NAME = "moodle"

# Course-module type -> observation kind. None = not a piece of work or material
# (skipped, and counted in the snapshot notes).
MODULE_KIND = {
    "assign": "assignment", "quiz": "quiz", "lesson": "assignment", "workshop": "assignment",
    "h5pactivity": "assignment", "scorm": "assignment", "lti": "assignment", "choice": "assignment",
    "feedback": "assignment", "survey": "assignment", "data": "assignment", "glossary": "assignment",
    "page": "reading", "book": "reading", "resource": "reading", "url": "reading", "folder": "reading",
    "imscp": "reading",
    "forum": None, "label": None, "qbank": None, "subsection": None, "bigbluebuttonbn": "event",
    "chat": None, "wiki": None,
}
_EXAM_RE = re.compile(r"\b(exam|midterm|mid-term|final)s?\b", re.I)
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_MAX_MONTHS = 13


class MoodleError(RuntimeError):
    pass


def _ajax(session, base, sesskey, method, args):
    r = session.post(f"{base}/lib/ajax/service.php", params={"sesskey": sesskey, "info": method},
                     json=[{"index": 0, "methodname": method, "args": args}], timeout=30)
    r.raise_for_status()
    body = r.json()
    if isinstance(body, dict):          # whole-request failure (bad sesskey, not logged in)
        raise MoodleError(f"{method}: {body.get('errorcode') or body.get('error')}")
    res = body[0]
    if res.get("error"):
        exc = res.get("exception") or {}
        raise MoodleError(f"{method}: {exc.get('errorcode')}: {exc.get('message')}")
    return res["data"]


def _get(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def sesskey_from(page_html: str) -> str:
    m = re.search(r'"sesskey":"([^"]+)"', page_html)
    if not m:
        raise MoodleError("no sesskey on /my/: session is not logged in")
    return m.group(1)


def extract_links(fragment, base: str) -> tuple[str, ...]:
    """Every URL in an HTML fragment (hrefs and bare text) that points off this Moodle host."""
    if fragment is None:
        return ()
    host = (urlparse(base).hostname or "").lower(), urlparse(base).port
    found = [a.get("href", "") for a in fragment.find_all("a")]
    found += _URL_RE.findall(fragment.get_text(" "))
    out = []
    for u in found:
        u = htmllib.unescape(u.strip()).rstrip(".,;")
        # An instructor's typo must not fail the whole Moodle fetch. A broken IPv6 host
        # can't be parsed at all: skipped. A bad port ("h:99999") parses but has no port:
        # kept as written (off-host by definition), and fusion ignores it with a warning.
        try:
            p = urlparse(u)
        except ValueError:
            continue
        try:
            port = p.port
        except ValueError:
            port = "invalid"
        if p.scheme not in ("http", "https") or not p.hostname:
            continue
        if ((p.hostname or "").lower(), port) == host:
            continue            # same Moodle (autolinks, internal links): not cross-platform evidence
        if u not in out:
            out.append(u)
    return tuple(out)


def _excerpt(fragment) -> str | None:
    if fragment is None:
        return None
    text = re.sub(r"\s+", " ", fragment.get_text(" ")).strip()
    return text[:280] or None


def _cmid(url: str) -> str | None:
    q = parse_qs(urlparse(url or "").query)
    return q.get("id", [None])[0]


def _months(courses):
    """(year, month) pairs spanning the courses' start..end dates, capped."""
    starts = [c["startdate"] for c in courses if c.get("startdate")]
    if not starts:
        return []
    ends = [c["enddate"] for c in courses if c.get("enddate")]
    lo = datetime.fromtimestamp(min(starts), timezone.utc)
    hi = datetime.fromtimestamp(max(ends), timezone.utc) if ends else lo + timedelta(days=366)
    y, m, out = lo.year, lo.month, []
    while (y, m) <= (hi.year, hi.month) and len(out) < _MAX_MONTHS:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    # ponytail: only the courses' own date range (max 13 months) is scanned for
    # dated events; an assignment due outside its course dates shows as undated.
    # Upgrade path: also scan core_calendar_get_action_events_by_timesort with no bounds.
    return out


def _day_offsets(month_view) -> list[tuple[int, timezone]]:
    """[(local-midnight epoch, the server's UTC offset that day)] from a monthly view."""
    out = []
    for week in month_view.get("weeks", []):
        for day in week.get("days", []):
            wall = datetime(day["year"], 1, 1, tzinfo=timezone.utc) + timedelta(days=day["yday"])
            off = timedelta(seconds=round((wall.timestamp() - day["timestamp"]) / 60) * 60)
            out.append((day["timestamp"], timezone(off)))
    return out


def _at(ts: int, offsets) -> datetime:
    tz = timezone.utc
    for start, off in offsets:          # sorted ascending
        if start <= ts:
            tz = off
        else:
            break
    # ponytail: the offset is the one in force at local midnight of that day, so on
    # the DST-switch day an event after 02:00 carries the pre-switch offset. The
    # instant is still exact (it comes from the epoch). Upgrade path: take the
    # offset from the next day's midnight when the two differ and ts is past 02:00.
    return datetime.fromtimestamp(ts, tz)


def _parse_assign_page(html_text: str, base: str):
    soup = BeautifulSoup(html_text, "html.parser")
    intro = soup.find(id="intro") or soup.find(class_="activity-description")
    main = soup.find(attrs={"role": "main"}) or soup
    submit = None
    for form in main.find_all("form"):
        if form.find("input", attrs={"name": "action", "value": "editsubmission"}):
            cm = form.find("input", attrs={"name": "id"})
            if cm is not None:
                submit = f"{base}/mod/assign/view.php?id={cm.get('value')}&action=editsubmission"
    if submit is None:
        a = main.find("a", href=re.compile(r"action=editsubmission"))
        if a is not None:
            submit = htmllib.unescape(a["href"])
    # Status cells carry a language-independent class: submissionstatus<new|draft|submitted|reopened>.
    done = None
    cell = main.find("td", class_=re.compile(r"\bsubmissionstatus(new|draft|submitted|reopened)\b"))
    if cell is not None:
        done = "submissionstatussubmitted" in cell.get("class", [])
    elif submit is not None:
        done = False            # can still add a submission and nothing is submitted yet
    return {"links": extract_links(intro, base), "excerpt": _excerpt(intro), "submit_url": submit, "done": done}


def _parse_page_page(html_text: str, base: str):
    soup = BeautifulSoup(html_text, "html.parser")
    main = soup.find(attrs={"role": "main"}) or soup
    body = main.find(class_="generalbox") or main
    intro = soup.find(id="intro")
    links = extract_links(body, base) + extract_links(intro, base)
    return {"links": tuple(dict.fromkeys(links)), "excerpt": _excerpt(body), "submit_url": None, "done": None}


PAGE_PARSERS = {"assign": _parse_assign_page, "page": _parse_page_page}


def fetch(session: requests.Session, base: str) -> Snapshot:
    base = base.rstrip("/")
    notes: list[str] = []
    sesskey = sesskey_from(_get(session, f"{base}/my/"))

    def ajax(method, args):
        return _ajax(session, base, sesskey, method, args)

    # 1. courses. "allincludinghidden" also returns courses the student hid from
    # their dashboard; they're still enrolled and still have work due.
    raw_courses = ajax("core_course_get_enrolled_courses_by_timeline_classification",
                       {"classification": "allincludinghidden", "limit": 0, "offset": 0, "sort": "fullname"})["courses"]
    courses = tuple(sorted((CourseObservation(
        source=NAME, source_id=str(c["id"]), label=c["shortname"], title=c["fullname"],
        term_hint=None, url=c["viewurl"]) for c in raw_courses), key=lambda c: int(c.source_id)))
    course_ids = {c.source_id for c in courses}

    # 2. course modules (dated or not) from the course-format state.
    cms: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    for c in courses:
        state = ajax("core_courseformat_get_state", {"courseid": int(c.source_id)})
        state = json.loads(state) if isinstance(state, str) else state
        for cm in state.get("cm", []):
            mod = cm.get("module")
            kind = MODULE_KIND.get(mod, mod)
            if kind is None:
                skipped[mod] = skipped.get(mod, 0) + 1
                continue
            if not cm.get("uservisible") and not cm.get("hascmrestrictions"):
                continue        # hidden from this student
            cms[str(cm["id"])] = {"course": c.source_id, "module": mod, "kind": kind, "title": cm["name"],
                                  "url": cm.get("url") or f"{base}/mod/{mod}/view.php?id={cm['id']}",
                                  "due": None, "opens": None, "submit_url": None, "done": None,
                                  "links": (), "excerpt": None, "restricted": not cm.get("uservisible")}
    if skipped:
        notes.append("skipped non-work modules: " + ", ".join(f"{k}={v}" for k, v in sorted(skipped.items())))

    # 3. calendar, month by month over the courses' dates.
    events: dict[int, dict] = {}
    offsets: list[tuple[int, timezone]] = []
    for y, m in _months(raw_courses):
        view = ajax("core_calendar_get_calendar_monthly_view",
                    {"year": y, "month": m, "courseid": 1, "categoryid": 0, "includenavigation": False,
                     "mini": False, "day": 1})
        offsets += _day_offsets(view)
        for week in view.get("weeks", []):
            for day in week.get("days", []):
                for ev in day.get("events", []):
                    events.setdefault(ev["id"], ev)       # multi-day events repeat per day
    offsets.sort(key=lambda t: t[0])

    items: list[Observation] = []
    other_events = 0
    for ev in sorted(events.values(), key=lambda e: e["id"]):
        cid = str((ev.get("course") or {}).get("id", ""))
        when = _at(ev["timestart"], offsets)
        if ev.get("modulename"):
            cm = cms.get(_cmid(ev.get("url")) or "")
            if cm is None:
                other_events += 1
                continue
            et = ev.get("eventtype")
            if et in ("due", "close"):
                cm["due"] = when
            elif et == "open":
                cm["opens"] = when
            act = (ev.get("action") or {}).get("url") or ""
            if "action=editsubmission" in act:
                cm["submit_url"] = htmllib.unescape(act)
            continue
        if cid not in course_ids or ev.get("eventtype") not in ("course", "group"):
            other_events += 1
            continue
        frag = BeautifulSoup(ev.get("description") or "", "html.parser")
        items.append(Observation(
            source=NAME, source_id=f"event:{ev['id']}", course_source_id=cid,
            kind="exam" if _EXAM_RE.search(ev["name"]) else "event", title=ev["name"],
            due=when, opens=None, url=ev.get("viewurl") or ev.get("url"),
            links_out=extract_links(frag, base), excerpt=_excerpt(frag)))
    if other_events:
        notes.append(f"skipped {other_events} calendar events not tied to a course item (user/site/category)")

    # 4. each assignment / page's own page: description links, submit button, done.
    # ponytail: GET mod/assign/view.php makes Moodle insert a status "new"
    # submission row for the student (exactly what their browser does when they
    # open it; no grade or "submitted" effect). No AJAX function exposes the
    # description or submission state to a browser session. Upgrade path: where a
    # school enables the mobile web service, use a token and
    # mod_assign_get_assignments / mod_assign_get_submission_status instead.
    for cmid, cm in cms.items():
        parser = PAGE_PARSERS.get(cm["module"])
        if parser is None or cm["restricted"]:
            continue
        got = parser(_get(session, cm["url"]), base)
        cm["links"], cm["excerpt"], cm["done"] = got["links"], got["excerpt"], got["done"]
        # The page is the authority on submitting. The calendar's "Add submission"
        # action is offered even on assignments with no submission plugin enabled
        # (seen on 4.5 for "WeBWorK HW1"), so it's only a fallback for unfetched pages.
        cm["submit_url"] = got["submit_url"]
        if cm["submit_url"] and cm["submit_url"].startswith("/"):
            cm["submit_url"] = base + cm["submit_url"]

    for cmid, cm in sorted(cms.items(), key=lambda kv: int(kv[0])):
        items.append(Observation(
            source=NAME, source_id=f"cm:{cmid}", course_source_id=cm["course"], kind=cm["kind"],
            title=cm["title"], due=cm["due"], opens=cm["opens"], url=cm["url"],
            submit_url=cm["submit_url"], links_out=cm["links"], done=cm["done"], excerpt=cm["excerpt"]))

    items.sort(key=lambda o: (int(o.course_source_id), o.source_id))
    return Snapshot(source=NAME, base=base, fetched_at=datetime.now(timezone.utc),
                    courses=courses, items=tuple(items), notes=tuple(notes))
