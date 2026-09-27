"""Canvas adapter: what an enrolled student can read, as that student.

UNVERIFIED: written from Canvas's public REST API docs
(https://canvas.instructure.com/doc/api/) and never run against a live Canvas
(no published image; a source build does not fit the spike machine).

The session is a browser-captured cookie session (the SSO path), so every
JSON body may start with Canvas's anti-JSON-hijacking prefix "while(1);".
It is stripped when present; a token session (no prefix) works too.

1. GET /api/v1/courses?include[]=term          the student's courses + terms
2. GET /api/v1/planner/items?start_date&end_date
                                               everything on the student planner
                                               (assignments, quizzes, discussions,
                                               pages, events, announcements, notes)
3. GET the item's own API object, only when the planner item carries no body
   (the planner's assignment "plannable" has no description), for links_out.

Every list follows the Link header's rel="next" (opaque, absolute URLs).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from fusion.model import CourseObservation, Observation, Snapshot

NAME = "canvas"

PREFIX = "while(1);"

# planner plannable_type -> our kind
KIND_FOR = {
    "assignment": "assignment",
    "sub_assignment": "assignment",      # discussion checkpoints
    "quiz": "quiz",
    "discussion_topic": "discussion",
    "wiki_page": "reading",
    "announcement": "announcement",
    "calendar_event": "event",
    "assessment_request": "peer_review",
    "planner_note": "note",
}

# plannable_type -> API path template for the full object (and its body field)
DETAIL = {
    "assignment": ("/api/v1/courses/{course}/assignments/{id}", "description"),
    "sub_assignment": ("/api/v1/courses/{course}/assignments/{id}", "description"),
    "quiz": ("/api/v1/courses/{course}/quizzes/{id}", "description"),
    "discussion_topic": ("/api/v1/courses/{course}/discussion_topics/{id}", "message"),
    "announcement": ("/api/v1/courses/{course}/discussion_topics/{id}", "message"),
}
BODY_KEYS = ("description", "message", "details", "body")

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def parse_json(text: str):
    """Canvas JSON, with the cookie-session 'while(1);' prefix removed if present."""
    t = text.lstrip()
    if t.startswith(PREFIX):
        t = t[len(PREFIX):]
    return json.loads(t)


def next_link(resp: requests.Response) -> str | None:
    """rel="next" from the Link header. requests' header dict is case-insensitive."""
    header = resp.headers.get("Link") or ""
    for part in header.split(","):
        m = re.match(r'\s*<([^>]+)>\s*;(.*)', part)
        if m and re.search(r'rel\s*=\s*"?next"?', m.group(2), re.I):
            return m.group(1)
    return None


TIMEOUT = 30                              # seconds; a server that never answers must not hang run.py


def get_json(session, url, params=None):
    r = session.get(url, params=params, headers={"Accept": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r, parse_json(r.text)


def get_all(session, url, params=None) -> list:
    """Every page of a paginated list, following Link rel=next."""
    out = []
    seen = set()
    while url:
        r, data = get_json(session, url, params)
        if not isinstance(data, list):
            raise ValueError(f"expected a JSON list from {url}")
        out.extend(data)
        params = None                    # next links are opaque and already carry every param
        url = next_link(r)
        if url in seen:                  # a server looping its bookmark must not hang the fetch
            break
        seen.add(url)
    return out


def _dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else None


def links_out(body_html: str | None, base: str) -> tuple[str, ...]:
    """Every http(s) URL in the body (hrefs, srcs and bare text) on a host other than Canvas's."""
    if not body_html:
        return ()
    soup = BeautifulSoup(body_html, "html.parser")
    urls = []
    for tag in soup.find_all(["a", "iframe", "img", "embed", "source"]):
        for attr in ("href", "src"):
            if tag.get(attr):
                try:
                    urls.append(urljoin(base + "/", tag[attr].strip()))
                except ValueError:       # e.g. a broken IPv6 host: not a usable link
                    continue
    urls += _URL_RE.findall(soup.get_text(" "))
    own = urlparse(base).netloc.lower()
    out = []
    for u in urls:
        try:
            p = urlparse(u)
        except ValueError:
            continue
        # a bad port ("http://h:99999/x") parses; it is kept as the instructor wrote it and
        # fuse.normalize_url ignores it for link evidence (with a warning)
        if p.scheme in ("http", "https") and p.netloc.lower() != own and u not in out:
            out.append(u)
    return tuple(out)


def _excerpt(body_html):
    if not body_html:
        return None
    text = " ".join(BeautifulSoup(body_html, "html.parser").get_text(" ").split())
    return text[:280] or None


def _done(item) -> bool | None:
    override = item.get("planner_override") or {}
    if override.get("marked_complete"):
        return True
    subs = item.get("submissions")
    if not isinstance(subs, dict):       # false = no associated assignment: Canvas can't tell
        return None
    return bool(subs.get("submitted") or subs.get("excused"))


def _course_obs(c, base) -> CourseObservation:
    term = c.get("term") or {}
    return CourseObservation(
        source=NAME,
        source_id=str(c["id"]),
        # access-restricted courses come back with only id + name
        label=c.get("course_code") or c.get("name") or str(c["id"]),
        title=c.get("original_name") or c.get("name") or "",
        term_hint=term.get("name"),
        url=urljoin(base + "/", f"courses/{c['id']}"),
    )


def _date_range(courses, now):
    """Planner window: the union of the student's term dates, else now -120 d .. now +365 d."""
    starts = [_dt((c.get("term") or {}).get("start_at")) for c in courses]
    ends = [_dt((c.get("term") or {}).get("end_at")) for c in courses]
    starts = [s for s in starts if s]
    ends = [e for e in ends if e]
    # ponytail: default terms ("Default Term") have no dates, and a term's dates
    # can be narrower than a course's own start_at/end_at overrides. Upgrade:
    # also union course start_at/end_at, and query per-course context_codes[].
    start = min(starts) if starts else now - timedelta(days=120)
    end = max(ends) if ends else now + timedelta(days=365)
    return start, end


def _iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(session: requests.Session, base: str, now: datetime | None = None) -> Snapshot:
    base = base.rstrip("/")
    now = now or datetime.now(timezone.utc)
    notes = []

    raw_courses = get_all(session, f"{base}/api/v1/courses",
                          {"include[]": "term", "per_page": 100})
    courses = {str(c["id"]): _course_obs(c, base) for c in raw_courses}

    start, end = _date_range(raw_courses, now)
    planner = get_all(session, f"{base}/api/v1/planner/items",
                      {"start_date": _iso(start), "end_date": _iso(end), "per_page": 50})

    items = []
    for it in planner:
        ptype = it.get("plannable_type") or ""
        plannable = it.get("plannable") or {}
        pid = str(it.get("plannable_id") or plannable.get("id"))

        if it.get("course_id") is not None:
            csid = str(it["course_id"])
        elif it.get("group_id") is not None:
            csid = f"group_{it['group_id']}"
        else:
            csid = "user"
        if csid not in courses:
            # ponytail: groups and personal notes get a stand-in course the fusion
            # core can't parse (so they stay separate, with a warning). Upgrade:
            # resolve a group to its parent course via /api/v1/groups/:id.
            courses[csid] = CourseObservation(
                source=NAME, source_id=csid,
                label=it.get("context_name") or ("Personal" if csid == "user" else csid),
                title=it.get("context_name") or "", term_hint=None,
                url=urljoin(base + "/", it.get("html_url") or "") if csid != "user" else base + "/")
            notes.append(f"planner item {ptype}:{pid} in context {csid} outside the course list")

        body = next((plannable.get(k) for k in BODY_KEYS if plannable.get(k)), None)
        detail = None
        if body is None and ptype in DETAIL and it.get("course_id") is not None:
            path, key = DETAIL[ptype]
            obj_id = plannable.get("assignment_id") if ptype == "sub_assignment" else pid
            try:
                _, detail = get_json(session, base + path.format(course=it["course_id"], id=obj_id or pid))
                body = detail.get(key)
            except (requests.RequestException, ValueError) as e:
                notes.append(f"could not read body of {ptype}:{pid}: {e}")

        kind = KIND_FOR.get(ptype, ptype or "item")
        if detail and "online_quiz" in (detail.get("submission_types") or []):
            kind = "quiz"
        if ptype not in KIND_FOR:
            notes.append(f"unknown plannable_type {ptype!r} kept as kind {kind!r}")

        due = None if ptype == "announcement" else _dt(it.get("plannable_date"))
        # ponytail: unlock_at only comes from the fetched detail object (assignments,
        # quizzes); undetailed types never get opens. Upgrade: read discussion
        # delayed_post_at / page publish_at.
        opens = _dt((detail or {}).get("unlock_at") or plannable.get("unlock_at"))

        html_url = it.get("html_url") or (detail or {}).get("html_url") or ""
        pts = plannable.get("points_possible")
        items.append(Observation(
            source=NAME,
            source_id=f"{ptype}:{pid}",
            course_source_id=csid,
            kind=kind,
            title=plannable.get("title") or plannable.get("name") or (detail or {}).get("name") or "",
            due=due,
            opens=opens,
            url=urljoin(base + "/", html_url),
            # the student submits on the item's own page; external-tool work is
            # submitted in the tool, which links_out points at
            submit_url=None,
            links_out=links_out(body, base),
            done=_done(it),
            # ponytail: weight needs assignment-group weights (/assignment_groups)
            # and points; not fetched. Upgrade: compute when apply_assignment_group_weights.
            weight=None,
            excerpt=_excerpt(body) or (f"{pts} pts" if pts is not None else None),
        ))

    return Snapshot(source=NAME, base=base, fetched_at=now,
                    courses=tuple(courses.values()), items=tuple(items), notes=tuple(notes))
