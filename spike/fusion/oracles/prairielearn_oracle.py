"""Live oracle: PrairieLearn adapter output vs the server's own ground truth.

Ground truth comes from PrairieLearn's Postgres (docker exec psql): the synced
assessments, their sets and their access rules as stored instants. That is a
different path from the adapter's (student HTML, rendered dates + printed zone).
It is also checked against SCENARIO.md's literal values.

    uv run python oracles/prairielearn_oracle.py [--save-fixtures] [--no-click]

Side effect (like a student clicking the row): the url check GETs each item's
url as fstudent. For the Homework "Problem Set 3" that starts an assessment
instance, after which PL links the row to /assessment_instance/<n>/. The oracle
then re-fetches and checks the adapter's source_id stayed stable. Exam-type
quizzes only show a "Start assessment" page on GET, so they stay unstarted.
--no-click skips that GET for unstarted Homework. up.sh resets everything.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fusion import snapshot_io  # noqa: E402
from fusion.adapters import prairielearn as adapter  # noqa: E402
from oracles.prairielearn.login import login, read_secrets  # noqa: E402

BASE = "http://127.0.0.1:3100"
CONTAINER = "fx-prairielearn"
VAN = ZoneInfo("America/Vancouver")
FIXTURES = ROOT / "fixtures" / "prairielearn"

# SCENARIO.md, PrairieLearn part. Wall-clock America/Vancouver.
SCENARIO = {
    "quiz1": dict(id="P1", title="Quiz 1", kind="quiz", due=(2026, 10, 2, 23, 59), opens=None),
    "ps3": dict(id="P2", title="Problem Set 3", kind="homework", due=(2026, 10, 5, 17, 0), opens=None),
    "quiz2": dict(id="P3", title="Quiz 2", kind="quiz", due=(2026, 10, 16, 23, 59), opens=None),
    "lab4": dict(id="P4", title="Lab 4", kind="lab", due=(2026, 10, 27, 23, 59), opens=(2026, 10, 20, 0, 0)),
}
SCENARIO_LINKS = {}   # SCENARIO gives no PrairieLearn item a link to another platform

fails = 0


def out(status, msg):
    global fails
    if status == "FAIL":
        fails += 1
    print(f"{status} {msg}")


def check(ok, msg, info=None):
    out("PASS" if ok else "FAIL", msg + ("" if ok or info is None else f": {info}"))


def van(t):
    return datetime(*t, tzinfo=VAN) if t else None


def psql_json(sql):
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "psql", "-U", "postgres", "-At"],
                       input=f"select coalesce(json_agg(t), '[]') from ({sql}) t;", capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def ts(s):
    return datetime.fromisoformat(s) if s else None


class Recorder:
    """Wraps a requests.Session and keeps every GET the adapter made."""

    def __init__(self, session):
        self.s, self.log = session, []

    def get(self, url, **kw):
        r = self.s.get(url, **kw)
        self.log.append((url, r.status_code, r.text))
        return r


def ground_truth():
    ci = psql_json("""
        select ci.id, ci.short_name as ci_short, ci.long_name, ci.display_timezone, c.short_name, c.title,
               c.display_timezone as course_tz
        from course_instances ci join courses c on c.id = ci.course_id
        where c.short_name = 'CPSC 121' and ci.short_name = '2026W1' and ci.deleted_at is null""")[0]
    rows = psql_json(f"""
        select a.id, a.tid, a.title, a.type, a.number, s.abbreviation, s.name as set_name, s.heading,
               (select json_agg(json_build_object('credit', r.credit, 'start', r.start_date, 'end', r.end_date,
                                                  'active', r.active) order by r.number)
                  from assessment_access_rules r where r.assessment_id = a.id) as rules
        from assessments a join assessment_sets s on s.id = a.assessment_set_id
        where a.course_instance_id = {ci['id']} and a.deleted_at is null order by a.tid""")
    enrolled = psql_json(f"""
        select e.status from enrollments e join users u on u.id = e.user_id
        where e.course_instance_id = {ci['id']} and u.uid = 'fstudent@example.invalid'""")
    return ci, {r["tid"]: r for r in rows}, enrolled


def truth_due_opens(rules):
    full = [r for r in rules if r["credit"] is not None and r["credit"] >= 100 and r["end"]]
    due = max(ts(r["end"]) for r in full) if full else None
    starts = [ts(r["start"]) for r in rules if r["start"] and (r["credit"] or 0) > 0]
    return due, (min(starts) if starts else None)


def own_page(session, url, label, title):
    """GET url as the student; returns (status, is_that_items_page, final_url, text)."""
    r = session.get(url, timeout=30)
    # Exam start / 403 pages put "Q1: Quiz 1" in <title>; instance pages only in the <h1>.
    heads = re.findall(r"<title>(.*?)</title>|<h1[^>]*>(.*?)</h1>", r.text, flags=re.S)
    heads = [" ".join(re.sub(r"<[^>]+>", " ", a or b).split()) for a, b in heads]
    return r.status_code, any(f"{label}: {title}" in h for h in heads), r.url, r.text


def run(click: bool, save: bool):
    sec = read_secrets(ROOT / "oracles" / "prairielearn" / "secrets.env")
    session = login(BASE, sec)
    ci, truth, enrolled = ground_truth()
    ci_id = str(ci["id"])
    check(enrolled == [{"status": "joined"}], "fstudent is enrolled (joined) in CPSC 121 / 2026W1", enrolled)
    check(ci["display_timezone"] == "America/Vancouver" and ci["course_tz"] == "America/Vancouver",
          "course and instance timezone are America/Vancouver", (ci["course_tz"], ci["display_timezone"]))
    check(set(truth) == set(SCENARIO), "server holds exactly the SCENARIO assessments", sorted(truth))
    for tid, sc in SCENARIO.items():
        t = truth[tid]
        due, opens = truth_due_opens(t["rules"])
        check(t["title"] == sc["title"], f"server {tid} title is {sc['title']!r}", t["title"])
        check(due == van(sc["due"]), f"server {tid} 100%-credit end is SCENARIO's {sc['due']}", due)
        if sc["opens"]:
            check(opens == van(sc["opens"]), f"server {tid} opens at SCENARIO's {sc['opens']}", opens)

    snap = adapter.fetch(session, BASE)
    check(snap.source == "prairielearn", "snapshot source is prairielearn")
    for n in snap.notes:
        out("INFO", f"adapter note: {n}")

    # Courses
    check(len(snap.courses) == 1, "one course observation", [c.label for c in snap.courses])
    c = snap.courses[0]
    check(c.source_id == ci_id, "course source_id is the course instance id", c.source_id)
    check(c.label == f"{ci['short_name']}, {ci['ci_short']}", "course label = PL short names", c.label)
    check(c.title == f"{ci['short_name']}: {ci['title']}, {ci['long_name']}", "course title = PL names", c.title)
    check(c.term_hint == ci["long_name"] == "2026 Winter Term 1", "course term_hint", c.term_hint)
    out("INFO", f"course label={c.label!r} title={c.title!r}")

    by_title = {i.title: i for i in snap.items}
    scenario_titles = {sc["title"] for sc in SCENARIO.values()}
    for extra in sorted(set(by_title) - scenario_titles):
        out("INFO", f"extra observation not in SCENARIO: {extra!r}")
    check(len(snap.items) == len(by_title), "no duplicate titles among items")

    source_ids = {}
    for tid, sc in SCENARIO.items():
        t = truth[tid]
        it = by_title.get(sc["title"])
        if it is None:
            out("FAIL", f"{sc['id']} {sc['title']!r} missing from adapter output")
            continue
        label = f"{t['abbreviation']}{t['number']}"
        source_ids[tid] = it.source_id
        due, opens = truth_due_opens(t["rules"])
        check(it.source_id == f"{ci_id}:{label}", f"{sc['id']} source_id is <ci>:<set label>", it.source_id)
        check(it.course_source_id == ci_id, f"{sc['id']} course_source_id", it.course_source_id)
        check(it.kind == sc["kind"], f"{sc['id']} kind {sc['kind']!r} (set {t['heading']!r})", it.kind)
        for name, v in (("due", it.due), ("opens", it.opens)):
            check(v is None or (v.tzinfo is not None and v.utcoffset() is not None), f"{sc['id']} {name} is tz-aware", v)
        check(it.due == due, f"{sc['id']} due instant == DB 100%-credit end {due.isoformat() if due else None}", it.due)
        check(it.due == van(sc["due"]), f"{sc['id']} due == SCENARIO {sc['due']} America/Vancouver", it.due)
        check(it.due is not None and it.due.utcoffset() == timedelta(hours=-7), f"{sc['id']} due printed as PDT (-07:00)",
              it.due and it.due.tzname())
        check(it.opens == opens, f"{sc['id']} opens == DB availability start {opens.isoformat() if opens else None}", it.opens)
        if sc["opens"]:
            check(it.opens == van(sc["opens"]), f"{sc['id']} opens == SCENARIO {sc['opens']}", it.opens)
            check(it.opens > datetime.now(timezone.utc), f"{sc['id']} is not open yet (opens in the future)")
        check(it.links_out == tuple(SCENARIO_LINKS.get(tid, ())), f"{sc['id']} links_out as SCENARIO", it.links_out)
        check(urlparse(it.url).netloc == urlparse(BASE).netloc, f"{sc['id']} url on the PL server", it.url)

        # url: the item's own page, 200 for the student
        deep = f"{BASE}/pl/course_instance/{ci_id}/assessment/{t['id']}/"
        path = urlparse(it.url).path
        if re.fullmatch(rf"/pl/course_instance/{ci_id}/assessment/{t['id']}/?", path):
            if t["type"] == "Homework" and not click:
                out("INFO", f"{sc['id']} url is the deep link {it.url}; not GET-checked (--no-click; it would start the homework)")
                continue
            before = psql_json(f"select id from assessment_instances where assessment_id = {t['id']}")
            status, own, final, _ = own_page(session, it.url, label, t["title"])
            after = psql_json(f"select id from assessment_instances where assessment_id = {t['id']}")
            check(status == 200 and own, f"{sc['id']} url returns 200 and is {label}: {t['title']}'s own page",
                  (status, final))
            if after != before:
                out("INFO", f"{sc['id']} GET of {it.url} started an assessment instance (PL does that for Homework); "
                            f"student now lands on {final}")
        elif re.fullmatch(rf"/pl/course_instance/{ci_id}/assessment_instance/\d+/?", path):
            inst = psql_json(f"""select ai.id from assessment_instances ai join users u on u.id = ai.user_id
                                 where ai.assessment_id = {t['id']} and u.uid = 'fstudent@example.invalid'""")
            iid = path.rstrip("/").rsplit("/", 1)[-1]
            check(any(str(x["id"]) == iid for x in inst), f"{sc['id']} url is fstudent's own instance of {tid}", it.url)
            status, own, final, _ = own_page(session, it.url, label, t["title"])
            check(status == 200 and own, f"{sc['id']} instance url returns 200 and is {label}'s page", (status, final))
        else:
            # Not yet linked for the student (not open): the adapter can't see the id.
            check(path.rstrip("/") == f"/pl/course_instance/{ci_id}/assessments" and sc["opens"],
                  f"{sc['id']} unlinked (not open) row falls back to the assessments page", it.url)
            status, own, final, text = own_page(session, deep, label, t["title"])
            m = re.search(r"will become available on ([^<]+?)\.\s*<", text)
            out("INFO", f"{sc['id']} real deep link {deep} gives the student HTTP {status} "
                        f"({'its own page' if own else 'other page'}): 'will become available on {m.group(1) if m else '?'}'")
            if m:
                check(adapter.parse_pl_date(m.group(1)) == it.opens,
                      f"{sc['id']} the 403 page's printed availability date equals adapter opens", m.group(1))

    # After clicks: fetch again (recorded, for fixtures); identity must be stable.
    rec = Recorder(session)
    snap2 = adapter.fetch(rec, BASE)
    ids2 = {i.title: i.source_id for i in snap2.items}
    for tid, sc in SCENARIO.items():
        if tid in source_ids:
            check(ids2.get(sc["title"]) == source_ids[tid], f"{sc['id']} source_id stable across re-fetch", ids2.get(sc["title"]))
    for i in snap2.items:
        out("INFO", f"final {i.source_id} {i.kind} {i.title!r} due={i.due.isoformat() if i.due else None} "
                    f"opens={i.opens.isoformat() if i.opens else None} url={i.url}")

    if save:
        save_fixtures(rec.log, snap2)


def _fixture_name(url):
    p = urlparse(url).path.strip("/") or "root"
    return re.sub(r"[^A-Za-z0-9]+", "_", p).strip("_") + ".html"


def scrub(text):
    """Drop per-session CSRF tokens (signed with this server's random key) from captured pages."""
    text = re.sub(r'(name="__csrf_token" value=")[^"]*', r"\1REDACTED", text)
    text = re.sub(r'("csrfToken":")[^"]*', r"\1REDACTED", text)
    text = re.sub(r'(csrf[-_]?token["\']?\s*[:=]\s*["\'])[^"\']+', r"\1REDACTED", text, flags=re.I)
    text = re.sub(r'(id="test_csrf_token"[^>]*>)[^<]*', r"\1REDACTED", text)
    # any other PL signed token: <base64 hmac>.<base36 time>.<base64 json>
    return re.sub(r"[A-Za-z0-9_-]{40,}\.[a-z0-9]{6,}\.eyJ[A-Za-z0-9_-]*", "REDACTED", text)


def save_fixtures(log, snap):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for old in FIXTURES.glob("*.html"):
        old.unlink()
    index = {}
    for url, status, text in log:
        name = _fixture_name(url)
        (FIXTURES / name).write_text(scrub(text))
        index[urlparse(url).path] = {"file": name, "status": status}
    (FIXTURES / "index.json").write_text(json.dumps({"base": BASE, "pages": index}, indent=2, sort_keys=True) + "\n")
    snapshot_io.save(snap, ROOT / "fixtures" / "snapshots" / "prairielearn.json")
    out("INFO", f"saved {len(index)} raw pages to {FIXTURES.relative_to(ROOT)} and the snapshot to fixtures/snapshots/prairielearn.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-fixtures", action="store_true")
    ap.add_argument("--no-click", action="store_true", help="don't GET unstarted Homework urls (that starts them)")
    a = ap.parse_args()
    run(click=not a.no_click, save=a.save_fixtures)
    print(f"{'FAIL' if fails else 'PASS'} prairielearn oracle: {fails} failure(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
