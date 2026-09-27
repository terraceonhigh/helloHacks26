"""Integration oracle: the REAL hub.canvas._run against a REAL self-hosted Canvas.

Opt-in and networked, so it is not a pytest test (the filename doesn't match
test_*.py). Run it by hand:

    set -a; source .env; set +a      # CANVAS_BASE, CANVAS_TOKEN (student), CANVAS_ADMIN_TOKEN
    uv run python tests/live/canvas_selfhost_oracle.py

What it does:
1. Seeds (idempotently, everything named "[oracle] ...") edge-case data with
   the admin token: a lab-shell course sharing the lecture's code, a
   Canvas-style term name, due dates around Vancouver midnight and on
   2027-01-06, a quiz, a calendar event, an undated assignment, and one the
   student has submitted (and that gets graded).
2. Calls hub.canvas._run through a tiny requests-backed stand-in for
   Playwright's request context, with hub.canvas.BASE pointed at the server.
3. Checks what the adapter returns against the raw Canvas payloads it saw.
4. Saves the result with main's hub/db.py and with PR #41's
   (origin/swarm/fix-pr33, loaded via `git show`) and reports the course rows.

Prints PASS/FAIL per check and exits 1 if anything failed. Tokens are read
from the environment only and never printed.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub import canvas  # noqa: E402
from hub import db as main_db  # noqa: E402

BASE = os.environ["CANVAS_BASE"].rstrip("/")
STUDENT = os.environ["CANVAS_TOKEN"]
ADMIN = os.environ["CANVAS_ADMIN_TOKEN"]
TAG = "[oracle]"
VAN = ZoneInfo("America/Vancouver")
ACCOUNT = 1
LAB_CODE = "CPSC 121 L1A 2026W1"
TERM_NAME = "2026 Winter Term 1"
START, END = date(2026, 8, 1), date(2027, 3, 1)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not ok else ""))


def info(msg):
    print(f"INFO  {msg}")


# --- admin API helpers --------------------------------------------------------

def api(method, path, token=ADMIN, **data):
    r = requests.request(method, f"{BASE}/api/v1{path}", headers={"Authorization": f"Bearer {token}"},
                         data=data or None, timeout=30)
    if not r.ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
    return r.json()


def get_all(path, token=ADMIN, **params):
    url, out = f"{BASE}/api/v1{path}", []
    params.setdefault("per_page", 100)
    while url:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        r.raise_for_status()
        out += r.json()
        url, params = r.links.get("next", {}).get("url"), None
    return out


def ensure(existing, key, name, create):
    found = next((x for x in existing if x.get(key) == name), None)
    return found if found else create()


# --- seeding ------------------------------------------------------------------

def seed():
    me = api("GET", "/users/self", token=STUDENT)
    terms = requests.get(f"{BASE}/api/v1/accounts/{ACCOUNT}/terms", params={"per_page": 100},
                         headers={"Authorization": f"Bearer {ADMIN}"}, timeout=30).json()["enrollment_terms"]
    term = ensure(terms, "name", TERM_NAME, lambda: api(
        "POST", f"/accounts/{ACCOUNT}/terms", **{"enrollment_term[name]": TERM_NAME}))

    lab_name = f"{TAG} {LAB_CODE} Lab"
    course = ensure(get_all(f"/accounts/{ACCOUNT}/courses"), "name", lab_name, lambda: api(
        "POST", f"/accounts/{ACCOUNT}/courses", offer="true", **{
            "course[name]": lab_name, "course[course_code]": LAB_CODE, "course[term_id]": term["id"],
            "course[time_zone]": "America/Vancouver"}))
    cid = course["id"]
    if course.get("workflow_state") != "available":
        api("PUT", f"/courses/{cid}", **{"course[event]": "offer"})

    if not any(e["user_id"] == me["id"] for e in get_all(f"/courses/{cid}/enrollments")):
        api("POST", f"/courses/{cid}/enrollments", **{
            "enrollment[user_id]": me["id"], "enrollment[type]": "StudentEnrollment",
            "enrollment[enrollment_state]": "active", "enrollment[notify]": "false"})

    def van(*args):
        return datetime(*args, tzinfo=VAN).isoformat()

    wanted = {  # title -> due_at (None = no due date)
        f"{TAG} due 23:59 Vancouver": van(2026, 10, 15, 23, 59),
        f"{TAG} due 00:01 Vancouver": van(2026, 10, 16, 0, 1),
        f"{TAG} due 2027-01-06": van(2027, 1, 6, 23, 59),
        f"{TAG} no due date": None,
        f"{TAG} submitted": van(2026, 10, 20, 23, 59),
    }
    assignments = get_all(f"/courses/{cid}/assignments")
    ids = {}
    for title, due in wanted.items():
        a = ensure(assignments, "name", title, lambda title=title, due=due: api(
            "POST", f"/courses/{cid}/assignments", **{
                "assignment[name]": title, "assignment[published]": "true", "assignment[points_possible]": 10,
                "assignment[submission_types][]": "online_text_entry",
                **({"assignment[due_at]": due} if due else {})}))
        ids[title] = a["id"]

    quiz_title = f"{TAG} quiz"
    ensure(get_all(f"/courses/{cid}/quizzes"), "title", quiz_title, lambda: api(
        "POST", f"/courses/{cid}/quizzes", **{
            "quiz[title]": quiz_title, "quiz[due_at]": van(2026, 10, 17, 23, 59), "quiz[published]": "true"}))

    event_title = f"{TAG} lab office hours"
    events = get_all("/calendar_events", **{"context_codes[]": f"course_{cid}", "all_events": "true"})
    ensure(events, "title", event_title, lambda: api("POST", "/calendar_events", **{
        "calendar_event[context_code]": f"course_{cid}", "calendar_event[title]": event_title,
        "calendar_event[start_at]": van(2026, 10, 14, 15, 0), "calendar_event[end_at]": van(2026, 10, 14, 16, 0)}))

    sub_aid = ids[f"{TAG} submitted"]
    sub = api("GET", f"/courses/{cid}/assignments/{sub_aid}/submissions/{me['id']}")
    if not sub.get("submitted_at"):
        api("POST", f"/courses/{cid}/assignments/{sub_aid}/submissions", token=STUDENT, **{
            "submission[submission_type]": "online_text_entry", "submission[body]": "oracle submission"})
    api("PUT", f"/courses/{cid}/assignments/{sub_aid}/submissions/{me['id']}", **{"submission[posted_grade]": "8"})

    print(f"seeded: term {term['name']!r} (id {term['id']}), course {course['course_code']!r} (id {cid}), "
          f"{len(wanted)} assignments, 1 quiz, 1 event, 1 submission graded 8/10")


# --- the shim: Playwright-style request context over requests ------------------

class Resp:
    def __init__(self, r):
        self.status, self.ok, self._text = r.status_code, r.ok, r.text
        self.headers = {k.lower(): v for k, v in r.headers.items()}  # Playwright lower-cases header names

    def text(self):
        return self._text


class Req:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.log = []  # (url, parsed json) for every response the adapter saw

    def get(self, url):
        r = Resp(self.s.get(url, timeout=30))
        if r.ok:
            self.log.append((url, canvas.unwrap(r.text())))
        return r


# --- checks ---------------------------------------------------------------------

def parse_z(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def check_adapter():
    canvas.BASE = BASE  # monkeypatch only; no product-code change
    req = Req(STUDENT)
    courses, items = canvas._run(req, START, END)
    raw_courses = [c for u, page in req.log if "/api/v1/courses" in u for c in page]
    raw_plan = [p for u, page in req.log if "/api/v1/planner/items" in u for p in page]
    info(f"adapter returned {len(courses)} courses, {len(items)} items ({len(raw_plan)} raw planner items)")

    print("--- courses")
    check("one Course per raw Canvas course", len(courses) == len(raw_courses))
    for c, rc in zip(courses, raw_courses):
        enr = (rc.get("enrollments") or [{}])[0]
        want = (rc["course_code"], rc["term"]["name"], rc["name"], enr.get("computed_current_score"))
        check(f"course {rc['course_code']!r}: code/term/title/grade mapped",
              (c.code, c.term, c.title, c.grade) == want, f"got {(c.code, c.term, c.title, c.grade)}, want {want}")
        info(f"course {c.code!r}: term {c.term!r}, grade {c.grade!r}")
    lab = next((c for c in courses if c.code == LAB_CODE), None)
    check("lab shell grade populated from the graded submission", lab is not None and lab.grade is not None,
          f"lab={lab}")

    print("--- items (each vs the planner payload that produced it)")
    check("one Item per raw planner item", len(items) == len(raw_plan))
    codes = {c["id"]: c["course_code"] for c in raw_courses}
    for it, p in zip(items, raw_plan):
        ptype, pl = p["plannable_type"], p["plannable"]
        label = f"{ptype} {pl.get('title')!r}"
        check(f"{label}: due tz-aware", it.due is None or it.due.tzinfo is not None)
        canvas_due = pl.get("due_at") or (pl.get("start_at") if ptype == "calendar_event" else None)
        if canvas_due:
            check(f"{label}: due == Canvas instant {canvas_due}",
                  it.due is not None and it.due == parse_z(canvas_due), f"got {it.due}")
        want_kind = {"assignment": "assignment", "quiz": "quiz", "calendar_event": "event"}.get(ptype)
        if want_kind:
            want_cat = {"assignment": "task", "quiz": "deadline", "event": "deadline"}[want_kind]
            check(f"{label}: kind/category", (it.kind, it.category) == (want_kind, want_cat),
                  f"got {(it.kind, it.category)}")
        html = p.get("html_url", "")
        want_url = html if html.startswith("http") else BASE + html
        check(f"{label}: url absolute, correct, not doubled", it.url == want_url and it.url.count("://") == 1,
              f"got {it.url!r}, want {want_url!r}")
        check(f"{label}: course code", it.course == codes.get(p.get("course_id"), p.get("context_name", "")))

    print("--- seeded edge cases")

    def find(title):
        return next((it for it in items if it.title == title), None)

    for title, local in [(f"{TAG} due 23:59 Vancouver", (2026, 10, 15, 23, 59)),
                         (f"{TAG} due 00:01 Vancouver", (2026, 10, 16, 0, 1)),
                         (f"{TAG} due 2027-01-06", (2027, 1, 6, 23, 59))]:
        it = find(title)
        got = tuple(it.due.astimezone(VAN).timetuple()[:5]) if it and it.due else None
        check(f"{title!r}: in planner, shows as {local} Vancouver", got == local, f"got {got}")
    sub = find(f"{TAG} submitted")
    check("submitted assignment: done is True", sub is not None and sub.done is True,
          f"got {sub.done if sub else 'missing'}")
    quiz = find(f"{TAG} quiz")
    check("quiz reaches the adapter as kind 'quiz'", quiz is not None and quiz.kind == "quiz")
    ev = find(f"{TAG} lab office hours")
    check("calendar event reaches the adapter as kind 'event'", ev is not None and ev.kind == "event")
    info(f"undated assignment in adapter output: {'yes' if find(f'{TAG} no due date') else 'NO'} "
         "(it exists in Canvas; planner/items only returns dated things in start..end)")
    for it, p in zip(items, raw_plan):
        if p["plannable_type"] == "calendar_event":
            info(f"event {it.title!r}: raw html_url {p.get('html_url')!r}, submissions {p.get('submissions')!r}, "
                 f"done {it.done!r}")
    return courses, items


def load_pr41_db():
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", "origin/swarm/fix-pr33:hub/db.py"],
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return None
    path = Path(tempfile.mkdtemp()) / "db_pr41.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("db_pr41", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_db(label, dbmod, courses, items):
    conn = dbmod.connect(":memory:")
    dbmod.save(conn, courses, items)
    rows = dbmod.courses(conn)
    print(f"--- {label}: courses rows (code, term, title, grade)")
    for r in rows:
        print(f"      {r}")
    per_course = conn.execute("SELECT COALESCE(c.code, '(none)'), COUNT(*) FROM items i "
                              "LEFT JOIN courses c ON c.id = i.course_id GROUP BY 1").fetchall()
    info(f"[{label}] items per course row: {per_course}")
    orphans = [r[0] for r in conn.execute("SELECT title FROM items WHERE course_id IS NULL")]
    shown = {r[3] for r in dbmod.upcoming(conn)}
    dated = [i for i in items if i.due]
    # Judgment call, stated as a check: a lab shell and its lecture are
    # separate Canvas courses with separate grades, so merging them loses one.
    check(f"[{label}] every Canvas course keeps its own row (lab shell not merged into lecture)",
          len(rows) == len(courses), f"{len(courses)} Canvas courses -> {len(rows)} rows")
    want = {(c.title, c.grade) for c in courses}
    check(f"[{label}] every Canvas (title, grade) pair survives save() unchanged",
          want <= {(r[2], r[3]) for r in rows}, f"rows {[(r[2], r[3]) for r in rows]} vs Canvas {sorted(want)}")
    check(f"[{label}] no item saved without a course", not orphans, f"orphans {orphans}")
    check(f"[{label}] every dated item appears in upcoming()", all(i.title in shown for i in dated),
          f"missing {[i.title for i in dated if i.title not in shown]}")


def main():
    code = requests.get(f"{BASE}/login/canvas", timeout=15).status_code
    if code != 200:
        sys.exit(f"Canvas not up at CANVAS_BASE (login page -> {code}); not touching it.")
    seed()
    time.sleep(20)  # server caches assignment visibility ~15 s (see canvas-selfhost README)
    courses, items = check_adapter()
    check_db("main hub/db.py", main_db, courses, items)
    pr41 = load_pr41_db()
    if pr41 is None:
        info("origin/swarm/fix-pr33 not fetched; skipping PR #41 db comparison")
    else:
        check_db("PR #41 hub/db.py", pr41, courses, items)
    failed = results.count(False)
    print(f"\n{len(results) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
