"""Real-endpoint oracle for the Canvas calendar-feed path (issue #47).

The hosted site takes a student's pasted Canvas feed URL and parses it with
hub/ics.py. This checks that parse against the Canvas REST API on the team's
self-hosted Canvas. Opt-in and networked, so pytest never collects it:

    set -a; source .env; set +a      # CANVAS_BASE, CANVAS_TOKEN (student), CANVAS_ADMIN_TOKEN
    uv run python tests/live/canvas_feed_oracle.py [--candidate <git ref>] [--seed]

1. Reads the student's feed URL from GET /api/v1/users/self/profile
   (calendar.ics) and fetches it with NO auth header: the pasted link alone
   has to work.
2. Ground truth from the REST API as the student: every assignment
   (undated too) and every calendar event, per course, with html_url and
   due_at / start_at.
3. Parses the feed with the candidate hub.ics.parse: this checkout's, or
   `--candidate <ref>`'s hub/ics.py loaded from a temp git worktree (only
   ics.py comes from the ref; hub.models is this checkout's).
4. Per item: title (no " [COURSE]" suffix), course code, kind (from the
   VEVENT UID event-assignment-<id> / event-calendar-event-<id>), due
   (tz-aware, same instant as the API), url (the item's own deep link, not
   the generic /calendar?include_contexts=...), and (source, url) unique.
5. Runs tests/live/adapter_conformance.check on the parsed items.
6. API items missing from the feed are INFO (undated: a documented feed
   limit) or WARN (dated), never FAIL.
7. Prints a PASS/FAIL/WARN table and exits 1 on any FAIL.

`--seed` adds obviously fake data with the admin token (idempotent): a
"FAKE feed-oracle announcement", to show whether announcements reach the
feed. The variety the oracle needs (assignment, event, undated assignment,
a second course) is reported as WARN when missing.

The feed URL is a secret, like a token: it and the tokens are never printed.
"""
import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from icalendar import Calendar  # noqa: E402

from tests.live import adapter_conformance  # noqa: E402
from hub.models import Course  # noqa: E402

VAN = ZoneInfo("America/Vancouver")
SOURCE = "canvas"
UID_RE = re.compile(r"^event-(assignment|calendar-event)-(\d+)$")
COURSE_SUFFIX = re.compile(r"\s*\[(.+?)\]\s*$")
FAKE_ANNOUNCEMENT = "FAKE feed-oracle announcement"


@dataclass
class Truth:
    """One API item: an assignment or a calendar event."""
    kind: str  # "assignment" | "event"
    id: int
    title: str
    course: str  # course_code
    due: datetime | None  # tz-aware, from due_at / start_at
    url: str  # html_url
    submitted: bool = False


@dataclass
class Row:
    label: str
    cells: dict = field(default_factory=dict)  # check -> (status, detail)


@dataclass
class Result:
    rows: list  # per-item Rows
    notes: list  # (status, message)

    def fails(self):
        return sum(s == "FAIL" for r in self.rows for s, _ in r.cells.values()) + \
            sum(s == "FAIL" for s, _ in self.notes)


def _redact(s):
    return re.sub(r"feeds/calendars/[^\s'\"]+", "feeds/calendars/<secret>", str(s))


def _same_link(got, want):
    """Host + path + query equal; scheme ignored (a self-hosted Canvas behind
    http can still print https links). Fragment ignored."""
    g, w = urlparse(got), urlparse(want)
    return (g.hostname, g.port, g.path, g.query) == (w.hostname, w.port, w.path, w.query)


def compare(ics_text, items, truth, *, source=SOURCE):
    """Pure comparison. `items` is candidate parse(ics_text) output, `truth`
    a list[Truth]. Network-free; tests/test_canvas_feed_oracle.py drives it."""
    events = list(Calendar.from_ical(ics_text).walk("VEVENT"))
    by_key = {(t.kind, t.id): t for t in truth}
    rows, notes, seen = [], [], set()

    if len(items) != len(events):
        notes.append(("FAIL", f"parse returned {len(items)} items for {len(events)} VEVENTs"))

    for ev, it in zip(events, items):
        uid = str(ev.get("uid", ""))
        m = UID_RE.match(uid)
        row = Row(label=uid)
        rows.append(row)
        if not m:
            row.cells["match"] = ("WARN", f"UID {uid!r} is not an assignment/event; not checked")
            continue
        kind = "assignment" if m.group(1) == "assignment" else "event"
        t = by_key.get((kind, int(m.group(2))))
        if t is None:
            row.cells["match"] = ("WARN", f"{uid} in the feed but not in the API ground truth")
            continue
        seen.add((kind, t.id))
        row.label = f"{kind[:5]} {t.id} {t.title[:34]}"

        c = row.cells
        c["title"] = ("PASS", "") if it.title == t.title else ("FAIL", f"{it.title!r} != {t.title!r}")
        c["course"] = ("PASS", "") if it.course == t.course else ("FAIL", f"{it.course!r} != {t.course!r}")
        c["kind"] = ("PASS", "") if it.kind == kind else ("FAIL", f"{it.kind!r} != {kind!r}")

        raw = ev.get("dtstart").dt if ev.get("dtstart") else None
        d = it.due
        if not isinstance(d, datetime) or d.utcoffset() is None:
            c["due"] = ("FAIL", f"not a tz-aware datetime: {d!r}")
        elif t.due is None:
            c["due"] = ("WARN", "API has no due/start")
        elif isinstance(raw, date) and not isinstance(raw, datetime):
            # All-day VEVENT: the feed carries only a date. Same local date is the
            # most the feed can promise; an exact instant is a bonus.
            if d == t.due:
                c["due"] = ("PASS", "")
            elif d.astimezone(VAN).date() == t.due.astimezone(VAN).date():
                c["due"] = ("WARN", f"all-day feed item: date matches, instant {d.isoformat()} != {t.due.isoformat()}")
            else:
                c["due"] = ("FAIL", f"all-day date {d.astimezone(VAN).date()} != {t.due.astimezone(VAN).date()}")
        elif d == t.due:
            c["due"] = ("PASS", "")
        elif d.replace(second=0, microsecond=0) == t.due.replace(second=0, microsecond=0):
            c["due"] = ("PASS", "")  # Canvas's feed truncates seconds; noted once below
        else:
            c["due"] = ("FAIL", f"{d.isoformat()} != {t.due.isoformat()}")

        if _same_link(it.url, t.url):
            c["url"] = ("PASS", "")
        elif "/calendar" in urlparse(it.url).path and "event_id=" not in it.url:
            c["url"] = ("FAIL", f"generic calendar link, want {urlparse(t.url).path}"
                                + (f"?{urlparse(t.url).query}" if urlparse(t.url).query else ""))
        else:
            c["url"] = ("FAIL", f"{_redact(it.url)!r} != {t.url!r}")

    # seconds truncation note
    trunc = sum(1 for t in truth if t.due and t.due.second and (t.kind, t.id) in seen)
    if trunc:
        notes.append(("INFO", f"{trunc} feed item(s) lose the seconds of their API instant "
                              "(Canvas writes DTSTART to the minute); compared to the minute"))
    alldays = [str(e.get("uid")) for e in events
               if e.get("dtstart") and not isinstance(e.get("dtstart").dt, datetime)]
    if alldays:
        notes.append(("INFO", f"{len(alldays)} feed item(s) are all-day (DTSTART;VALUE=DATE, no time/zone): "
                              f"{alldays}; the parser must turn the date into a tz-aware instant"))

    # (source, url) identity
    urls = {}
    for it in items:
        urls.setdefault((it.source, it.url), []).append(it.title)
    dup = {k: v for k, v in urls.items() if len(v) > 1}
    if dup:
        n = sum(len(v) for v in dup.values())
        notes.append(("FAIL", f"(source, url) not unique: {n} items share {len(dup)} key(s), "
                              f"e.g. {list(dup.values())[0][:4]}"))
    else:
        notes.append(("PASS", f"(source, url) unique across {len(items)} items"))
    if any(it.source != source for it in items):
        notes.append(("FAIL", f"some items have source != {source!r}"))

    # missing from the feed
    for t in truth:
        if (t.kind, t.id) in seen:
            continue
        if t.due is None:
            notes.append(("INFO", f"not in feed (undated, documented feed limit): {t.kind} {t.id} {t.title!r}"))
        else:
            notes.append(("WARN", f"not in feed though dated: {t.kind} {t.id} {t.title!r} {t.due.isoformat()}"))
    return Result(rows, notes)


def print_table(result, out=print):
    cols = ["title", "course", "kind", "due", "url"]
    w = max([len(r.label) for r in result.rows] + [10])
    out(f"{'item':<{w}}  " + "  ".join(f"{c:<6}" for c in cols))
    for r in result.rows:
        if "match" in r.cells:
            out(f"{r.label:<{w}}  {r.cells['match'][0]}  {r.cells['match'][1]}")
            continue
        out(f"{r.label:<{w}}  " + "  ".join(f"{r.cells[c][0]:<6}" for c in cols))
    details = [(r.label, c, s, d) for r in result.rows for c, (s, d) in r.cells.items() if s != "PASS" and c != "match"]
    if details:
        out("")
        shown = {}
        for label, c, s, d in details:  # one line per distinct (check, detail shape), with a count
            key = (s, c, re.sub(r"\d+", "#", d))
            shown.setdefault(key, []).append((label, d))
        for (s, c, _), hits in shown.items():
            out(f"{s}  {c}: {hits[0][1]}  -- {hits[0][0]}" + (f"  (+{len(hits) - 1} more like it)" if len(hits) > 1 else ""))
    out("")
    for s, msg in result.notes:
        out(f"{s}  {msg}")


# --- network side -------------------------------------------------------------

def _api(base, token):
    import requests

    def get_all(path, **params):
        url, out = f"{base}/api/v1{path}", []
        params.setdefault("per_page", 100)
        while url:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
            r.raise_for_status()
            j = r.json()
            out += j if isinstance(j, list) else [j]
            url, params = r.links.get("next", {}).get("url"), None
        return out
    return get_all


def _when(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def ground_truth(base, token):
    get_all = _api(base, token)
    courses = get_all("/courses", **{"enrollment_state": "active"})
    truth, api_courses = [], []
    for c in courses:
        code = c.get("course_code", "")
        api_courses.append(Course(code=code, section="", term="", title=c.get("name", "")))
        for a in get_all(f"/courses/{c['id']}/assignments", **{"include[]": "submission"}):
            truth.append(Truth("assignment", a["id"], a["name"], code, _when(a.get("due_at")), a["html_url"],
                               bool((a.get("submission") or {}).get("submitted_at"))))
        for e in get_all("/calendar_events", type="event", all_events="true",
                         **{"context_codes[]": f"course_{c['id']}"}):
            truth.append(Truth("event", e["id"], e["title"], code, _when(e.get("start_at")), e["html_url"]))
        for d in get_all(f"/courses/{c['id']}/discussion_topics", only_announcements="true"):
            truth.append(Truth("announcement", d["id"], d["title"], code, _when(d.get("posted_at")), d["html_url"]))
    return api_courses, truth


def seed(base, admin, student):
    import requests
    h = {"Authorization": f"Bearer {admin}"}
    courses = _api(base, student)("/courses", enrollment_state="active")
    cid = courses[0]["id"]
    existing = _api(base, admin)(f"/courses/{cid}/discussion_topics", only_announcements="true")
    if not any(d["title"] == FAKE_ANNOUNCEMENT for d in existing):
        r = requests.post(f"{base}/api/v1/courses/{cid}/discussion_topics", headers=h, timeout=30, data={
            "title": FAKE_ANNOUNCEMENT, "message": "Fake data for tests/live/canvas_feed_oracle.py.",
            "is_announcement": "true", "published": "true"})
        r.raise_for_status()
        print(f"INFO  seeded {FAKE_ANNOUNCEMENT!r} in course {cid}")


def load_parse(candidate):
    """hub.ics.parse from this checkout, or from `candidate`'s hub/ics.py."""
    if candidate is None:
        from hub import ics
        return ics.parse, None
    tmp = Path(tempfile.mkdtemp(prefix="feedoracle-cand-"))
    wt = tmp / "wt"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(wt), candidate],
                   check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location("candidate_ics", wt / "hub" / "ics.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def cleanup():
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(wt)], capture_output=True)
    return mod.parse, cleanup


def main(argv=None):
    import requests
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidate", help="git ref whose hub/ics.py to test (default: this checkout)")
    ap.add_argument("--seed", action="store_true", help="add FAKE data with CANVAS_ADMIN_TOKEN first")
    a = ap.parse_args(argv)

    base = os.environ["CANVAS_BASE"].rstrip("/")
    student = os.environ["CANVAS_TOKEN"]
    if a.seed:
        seed(base, os.environ["CANVAS_ADMIN_TOKEN"], student)

    profile = _api(base, student)("/users/self/profile")[0]
    feed_url = (profile.get("calendar") or {}).get("ics")
    if not feed_url:
        print("FAIL  profile has no calendar.ics feed URL")
        return 1
    r = requests.get(feed_url, timeout=30)  # deliberately no Authorization header
    ok = r.status_code == 200 and "BEGIN:VCALENDAR" in r.text
    print(f"{'PASS' if ok else 'FAIL'}  feed fetched with no auth header (HTTP {r.status_code})")
    if not ok:
        return 1
    ics_text = r.text

    courses, truth = ground_truth(base, student)
    announcements = [t for t in truth if t.kind == "announcement"]
    truth = [t for t in truth if t.kind != "announcement"]

    parse, cleanup = load_parse(a.candidate)
    try:
        items = parse(ics_text, SOURCE)
    finally:
        if cleanup:
            cleanup()
    print(f"INFO  candidate: {a.candidate or 'this checkout'}; {len(items)} items parsed, "
          f"{len(truth)} API assignments/events")

    variety = {
        "a dated assignment": any(t.kind == "assignment" and t.due for t in truth),
        "a calendar event": any(t.kind == "event" for t in truth),
        "an undated assignment": any(t.kind == "assignment" and not t.due for t in truth),
        "a second course": len({t.course for t in truth}) > 1,
    }
    for what, have in variety.items():
        if not have:
            print(f"WARN  ground truth lacks {what}; run with --seed or add FAKE data")

    result = compare(ics_text, items, truth)
    print()
    print_table(result)

    # other feed limits worth knowing
    uids = {str(e.get("uid")) for e in Calendar.from_ical(ics_text).walk("VEVENT")}
    sub = [t for t in truth if t.submitted and f"event-assignment-{t.id}" in uids]
    if sub:
        print(f"INFO  {len(sub)} submitted assignment(s) are in the feed with no done/submitted field "
              f"(Item.done stays None): {[t.title for t in sub]}")
    for t in announcements:
        hit = any(t.title in str(e.get("summary", "")) for e in Calendar.from_ical(ics_text).walk("VEVENT"))
        print(f"INFO  announcement {t.title!r} {'IS' if hit else 'is NOT'} in the feed")
    feed_tz = Calendar.from_ical(ics_text).get("x-wr-timezone")
    print(f"INFO  feed calendar time zone: {feed_tz or 'none (no X-WR-TIMEZONE, no VTIMEZONE)'}; "
          f"profile time_zone {profile.get('time_zone')!r}")
    hosts = {urlparse(i.url).scheme for i in items if i.url}
    if hosts and urlparse(base).scheme not in hosts:
        print(f"INFO  feed links use {sorted(hosts)} but CANVAS_BASE is {urlparse(base).scheme} "
              "(self-host config); conformance base uses the feed's scheme")

    print()
    feed_base = base
    if items and items[0].url:
        p = urlparse(items[0].url)
        if p.hostname == urlparse(base).hostname:
            feed_base = f"{p.scheme}://{p.netloc}"
    findings = adapter_conformance.check(
        courses, items, base=feed_base, source=SOURCE, utc_ok=True,
        report_undated=sum(t.due is None for t in truth))
    conf_fails = adapter_conformance.report(findings, out=lambda s: print(_redact(s)))

    fails = result.fails() + conf_fails
    print(f"\n{'FAIL' if fails else 'PASS'}  canvas feed oracle: {fails} FAIL(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
