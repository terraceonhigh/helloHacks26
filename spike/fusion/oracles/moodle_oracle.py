"""Live oracle for the Moodle adapter.

Logs in as fstudent, runs fusion.adapters.moodle.fetch, and checks the output
against ground truth read straight from Moodle's Postgres database (a
different code path from anything the adapter touches) and against the Moodle
rows of SCENARIO.md.

    uv run python -m oracles.moodle_oracle                 # check
    uv run python -m oracles.moodle_oracle --save-fixtures # check + write fixtures/moodle/ and fixtures/snapshots/moodle.json

Prints PASS / FAIL / INFO lines, exits 1 on any FAIL.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fusion import snapshot_io
from fusion.adapters import moodle
from oracles.moodle.login import login, read_secrets
from oracles.moodle.replay import RecordingSession

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "oracles" / "moodle"
BASE = "http://localhost:8082"
VAN = ZoneInfo("America/Vancouver")

fails = 0


def say(level, msg):
    global fails
    if level == "FAIL":
        fails += 1
    print(f"{level} {msg}")


def check(ok, msg, detail=""):
    say("PASS" if ok else "FAIL", msg + ("" if ok else f"  [{detail}]"))
    return ok


def links_env():
    out = {}
    for line in (HERE / "links.env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def wall(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=VAN) if s else None


def scenario():
    L = links_env()
    ww = L["WW_BASE"].rstrip("/")
    M, C, E = "MATH100-2026W1", "CPSC121-101-2026W1", "ENGL110-001-2026W1"
    # id: (course shortname, title, kind, due wall-clock, links_out, has a Moodle submission)
    return {
        "M1": (M, "WeBWorK HW1", "assignment", "2026-09-20 23:59", [f"{ww}/HW1/"], False),
        "M2": (M, "Homework 2 (WeBWorK)", "assignment", "2026-09-29 23:00", [f"{ww}/HW2/"], False),
        "M3": (M, "Midterm 1", "exam", "2026-10-15 18:00", [], False),
        "M4": (M, "Assignment 1", "assignment", "2026-10-09 23:59", [], True),
        "M5": (C, "PrairieLearn Quiz 1", "assignment", None, [L["PL_QUIZ1_URL"]], False),
        "M6": (E, "Assignment 1", "assignment", "2026-10-09 23:59", [], True),
        "M7": (C, "Problem Set 3 due", "event", "2026-10-05 17:00", [], False),
        "M8": (C, "Quiz 3", "assignment", "2026-10-16 23:59", [], True),
        "M9": (E, "Reading: Chapter 4", "reading", None, [], False),
    }


COURSES = {"MATH100-2026W1": "MATH 100 Differential Calculus",
           "CPSC121-101-2026W1": "CPSC 121 101 Models of Computation",
           "ENGL110-001-2026W1": "ENGL 110 Approaches to Literature"}


def sql(query):
    out = subprocess.run(["docker", "exec", "fx-moodle-db", "psql", "-U", "moodle", "-d", "moodle", "-At", "-c",
                          f"select coalesce(json_agg(t), '[]') from ({query}) t"],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def ground_truth():
    tz = sql("select name, value from mdl_config where name in ('timezone','forcetimezone')")
    courses = sql("""select c.id, c.shortname, c.fullname from mdl_course c
        join mdl_enrol e on e.courseid = c.id join mdl_user_enrolments ue on ue.enrolid = e.id
        join mdl_user u on u.id = ue.userid where u.username = 'fstudent' and ue.status = 0 order by c.id""")
    ids = ",".join(str(c["id"]) for c in courses) or "0"
    cms = sql(f"""select cm.id, cm.course, cm.idnumber, m.name as mod, cm.visible,
          coalesce(a.name, p.name) as name, a.duedate, a.allowsubmissionsfromdate,
          coalesce(a.intro, p.content) as body,
          (select count(*) from mdl_assign_plugin_config pc where pc.assignment = a.id
             and pc.subtype = 'assignsubmission' and pc.name = 'enabled' and pc.value = '1'
             and pc.plugin in ('onlinetext','file')) as subplugins,
          (select s.status from mdl_assign_submission s join mdl_user u on u.id = s.userid
             where s.assignment = a.id and u.username = 'fstudent' and s.latest = 1) as substatus
        from mdl_course_modules cm join mdl_modules m on m.id = cm.module
        left join mdl_assign a on m.name = 'assign' and a.id = cm.instance
        left join mdl_page p on m.name = 'page' and p.id = cm.instance
        where cm.course in ({ids}) and cm.deletioninprogress = 0 order by cm.id""")
    events = sql(f"""select id, courseid, name, eventtype, timestart, description from mdl_event
        where courseid in ({ids}) and eventtype in ('course','group') order by id""")
    return {c["name"]: c["value"] for c in tz}, courses, cms, events


def offhost_links(body):
    urls = re.findall(r"https?://[^\s<>\"')\]]+", body or "")
    return sorted({u for u in urls if urlparse(u).netloc.lower() != urlparse(BASE).netloc.lower()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-fixtures", action="store_true")
    args = ap.parse_args()

    cfg, db_courses, db_cms, db_events = ground_truth()
    check(cfg.get("forcetimezone") == "America/Vancouver", "server forcetimezone is America/Vancouver", cfg)
    server_tz = ZoneInfo(cfg.get("forcetimezone") or cfg.get("timezone"))

    live = login(BASE, read_secrets())
    rec = RecordingSession(live)
    snap = moodle.fetch(rec, BASE)
    say("INFO", f"adapter returned {len(snap.courses)} courses, {len(snap.items)} items; notes={list(snap.notes)}")

    # --- courses ---------------------------------------------------------
    by_label = {c.label: c for c in snap.courses}
    for short, full in COURSES.items():
        c = by_label.get(short)
        db = next((d for d in db_courses if d["shortname"] == short), None)
        if check(c is not None and db is not None, f"course {short} present (adapter and DB enrolment)"):
            check(c.title == full == db["fullname"], f"course {short} fullname exact", c.title)
            check(c.source_id == str(db["id"]), f"course {short} source_id is DB id {db['id']}", c.source_id)
    check(len(snap.courses) == len(db_courses), "adapter course count == DB enrolments",
          f"{len(snap.courses)} vs {len(db_courses)}")
    cid_to_short = {c.source_id: c.label for c in snap.courses}

    for o in snap.items:
        for f in ("due", "opens"):
            v = getattr(o, f)
            if v is not None and v.tzinfo is None:
                say("FAIL", f"{o.source_id} {f} is naive: {v!r}")
    check(snap.fetched_at.tzinfo is not None, "fetched_at tz-aware")

    # --- SCENARIO items ---------------------------------------------------
    matched = set()
    for mid, (short, title, kind, due_s, links, has_sub) in scenario().items():
        cands = [o for o in snap.items if cid_to_short.get(o.course_source_id) == short and o.title == title]
        if not check(len(cands) == 1, f"{mid} {short} {title!r} present exactly once", len(cands)):
            continue
        o = cands[0]
        matched.add(o.source_id)
        exp_due = wall(due_s)
        check(o.kind == kind, f"{mid} kind == {kind}", o.kind)
        check(o.due == exp_due, f"{mid} due == SCENARIO {due_s}", o.due)
        if o.due is not None:
            check(o.due.utcoffset() == o.due.astimezone(server_tz).utcoffset(),
                  f"{mid} due carries the server's own offset", o.due.utcoffset())

        # independent DB row for this item
        if o.source_id.startswith("cm:"):
            cmid = int(o.source_id[3:])
            db = next((d for d in db_cms if d["id"] == cmid), None)
            if not check(db is not None and db["idnumber"] == f"fx-{mid}", f"{mid} is DB course module {cmid} (fx-{mid})", db):
                continue
            db_due = datetime.fromtimestamp(db["duedate"], VAN) if db.get("duedate") else None
            check(o.due == db_due, f"{mid} due == DB duedate", f"{o.due} vs {db_due}")
            db_open = datetime.fromtimestamp(db["allowsubmissionsfromdate"], VAN) if db.get("allowsubmissionsfromdate") else None
            check(o.opens == db_open, f"{mid} opens == DB allowsubmissionsfromdate", f"{o.opens} vs {db_open}")
            check(_cm_id(o.url) == cmid and f"/mod/{db['mod']}/view.php" in o.url, f"{mid} url is its own {db['mod']} page", o.url)
            check(sorted(o.links_out) == offhost_links(db["body"]) == sorted(links),
                  f"{mid} links_out == DB description links == SCENARIO", f"{o.links_out} / {offhost_links(db['body'])}")
            if db["mod"] == "assign":
                exp_done = True if db["substatus"] == "submitted" else (False if db["subplugins"] else None)
                check(o.done == exp_done, f"{mid} done == DB submission state ({db['substatus']}, plugins={db['subplugins']})", o.done)
                if db["subplugins"]:
                    q = parse_qs(urlparse(o.submit_url or "").query)
                    # ponytail: the submit page is checked by shape only. GETting it would make
                    # Moodle create a "new" submission row for fstudent (a write).
                    check(q.get("action") == ["editsubmission"] and q.get("id") == [str(cmid)],
                          f"{mid} submit_url is its editsubmission page", o.submit_url)
                else:
                    check(o.submit_url is None, f"{mid} no submit_url (nothing to submit on Moodle)", o.submit_url)
            check(bool(db["subplugins"]) == has_sub, f"{mid} DB submission setting matches SCENARIO", db["subplugins"])
            r = live.get(o.url, timeout=30)
            t = re.search(r"<title>(.*?)</title>", r.text, re.S)
            check(r.status_code == 200 and t and f"{short}: {title}" in t.group(1).replace("&amp;", "&"),
                  f"{mid} url returns 200 for the student and is that item's page", f"{r.status_code} {t and t.group(1)}")
        else:
            evid = int(o.source_id.split(":")[1])
            db = next((d for d in db_events if d["id"] == evid), None)
            if not check(db is not None and db["name"] == title, f"{mid} is DB event {evid}", db):
                continue
            check(o.due == datetime.fromtimestamp(db["timestart"], VAN), f"{mid} due == DB timestart", o.due)
            check(sorted(o.links_out) == offhost_links(db["description"]) == sorted(links), f"{mid} links_out", o.links_out)
            r = live.get(o.url, timeout=30)
            check(r.status_code == 200 and f'data-event-id="{evid}"' in r.text and title in r.text,
                  f"{mid} url returns 200 and shows event {evid}", r.status_code)
        check("/course/view.php" not in o.url, f"{mid} url is not a course home page", o.url)

    # --- everything else the adapter emitted, and DB items it missed -------
    for o in snap.items:
        if o.source_id not in matched:
            say("INFO", f"extra observation (not in SCENARIO): {o.source_id} {o.kind} {o.title!r} due={o.due}")
    emitted = {o.source_id for o in snap.items}
    for d in db_cms:
        if d["mod"] in ("assign", "page", "quiz") and d["visible"] and f"cm:{d['id']}" not in emitted:
            say("FAIL", f"DB module {d['id']} {d['mod']} {d['name']!r} missing from adapter output")
    for d in db_events:
        if f"event:{d['id']}" not in emitted:
            say("FAIL", f"DB course event {d['id']} {d['name']!r} missing from adapter output")

    if args.save_fixtures:
        home = rec.records.get("GET /my/", {}).get("text", "")
        rec.save(ROOT / "fixtures" / "moodle", moodle.sesskey_from(home) if home else None)
        snapshot_io.save(snap, ROOT / "fixtures" / "snapshots" / "moodle.json")
        say("INFO", f"saved {len(rec.records)} raw responses to fixtures/moodle/ and fixtures/snapshots/moodle.json")

    print(f"{'FAIL' if fails else 'PASS'} moodle oracle: {fails} failure(s)")
    return 1 if fails else 0


def _cm_id(url):
    try:
        return int(parse_qs(urlparse(url).query)["id"][0])
    except (KeyError, ValueError, IndexError):
        return None


if __name__ == "__main__":
    sys.exit(main())
