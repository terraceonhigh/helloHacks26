"""WeBWorK oracle: adapter output vs the server's own ground truth.

  uv run python oracles/webwork_oracle.py [--base http://localhost:8081] [--save-fixtures]

Ground truth is read straight from WeBWorK's MariaDB (docker exec into
fx-webwork-db), not through any page the adapter parses. Prints PASS/FAIL/INFO
lines, exits 1 on any FAIL. --save-fixtures writes the raw responses the
adapter parsed to fixtures/webwork/ and the Snapshot to fixtures/snapshots/webwork.json.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from fusion import snapshot_io  # noqa: E402
from fusion.adapters import webwork  # noqa: E402
from oracles.webwork.login import login, read_secrets  # noqa: E402

COURSE = "math100_2026w1"
DB_CONTAINER = "fx-webwork-db"
VAN = ZoneInfo("America/Vancouver")

# SCENARIO.md, WeBWorK part: id, set, open, due (wall clock, America/Vancouver).
SCENARIO = [
    ("W1", "HW1", "2026-09-01 00:00", "2026-09-20 23:59"),
    ("W2", "HW2", "2026-09-15 00:00", "2026-09-29 23:59"),
    ("W3", "HW9", "2026-12-01 00:00", "2027-01-15 23:59"),
    ("W4", "HW3", "2026-10-10 00:00", "2026-10-17 23:59"),
]

fails = 0


def out(level, msg):
    global fails
    if level == "FAIL":
        fails += 1
    print(f"{level} {msg}")


def check(ok, msg):
    out("PASS" if ok else "FAIL", msg)


class RecordingSession:
    """Wraps a requests.Session and keeps every GET body the adapter makes."""

    def __init__(self, s):
        self.s, self.log = s, []

    def get(self, url, **kw):
        r = self.s.get(url, **kw)
        self.log.append((url, r.status_code, r.url, r.text))
        return r


def db_truth(secrets) -> dict:
    """{set_id: {open, due, answer, visible, type}} as fstudent sees it (user overrides applied)."""
    sql = f"""
      SELECT g.set_id,
             COALESCE(u.open_date, g.open_date), COALESCE(u.due_date, g.due_date),
             COALESCE(u.answer_date, g.answer_date), COALESCE(u.visible, g.visible),
             COALESCE(u.assignment_type, g.assignment_type),
             FROM_UNIXTIME(COALESCE(u.due_date, g.due_date))
      FROM `{COURSE}_set` g JOIN `{COURSE}_set_user` u ON u.set_id = g.set_id AND u.user_id = 'fstudent'
      ORDER BY g.set_id"""
    res = subprocess.run(
        ["docker", "exec", "-i", "-e", f"MYSQL_PWD={secrets['WW_DB_PASSWORD']}", DB_CONTAINER,
         "mariadb", "-u", "webworkWrite", "-B", "-N", "webwork", "-e", sql],
        capture_output=True, text=True, check=True)
    truth = {}
    for line in res.stdout.strip().splitlines():
        sid, o, d, a, v, t, os_wall = line.split("\t")
        truth[sid] = {"open": int(o), "due": int(d), "answer": int(a), "visible": v == "1", "type": t,
                      "db_os_wall": os_wall}
    return truth


def wall(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8081")
    ap.add_argument("--save-fixtures", action="store_true")
    args = ap.parse_args()

    secrets = read_secrets()
    sess = login(args.base, secrets)
    rec = RecordingSession(sess)
    snap = webwork.fetch(rec, args.base)
    truth = db_truth(secrets)
    now = datetime.now(timezone.utc).timestamp()
    items = {i.source_id: i for i in snap.items}
    course_url = f"{args.base.rstrip('/')}/webwork2/{COURSE}"

    out("INFO", f"adapter: {len(snap.courses)} course(s), {len(snap.items)} item(s), notes={list(snap.notes)}")
    check(any(c.source_id == COURSE and c.label == COURSE for c in snap.courses),
          f"course {COURSE} observed with label {COURSE}")

    # Every set the DB says fstudent has (and can see) must be observed, and nothing else.
    visible = {sid for sid, t in truth.items() if t["visible"]}
    seen = {i.source_id.split("/", 1)[1] for i in snap.items if i.course_source_id == COURSE}
    check(visible == seen, f"observed sets == DB visible sets for fstudent ({sorted(visible)})")
    extras = seen - {s for _, s, _, _ in SCENARIO}
    if extras:
        out("INFO", f"extra sets beyond SCENARIO (listed, not dropped): {sorted(extras)}")

    for wid, set_id, open_s, due_s in SCENARIO:
        sid = f"{COURSE}/{set_id}"
        it = items.get(sid)
        if it is None:
            out("FAIL", f"{wid} {set_id}: missing from adapter output")
            continue
        t = truth.get(set_id)
        if t is None:
            out("FAIL", f"{wid} {set_id}: not in DB (seed broken?)")
            continue
        check(it.title == set_id, f"{wid} title {it.title!r} == {set_id!r}")
        exp_kind = "quiz" if "gateway" in (t["type"] or "") else "homework"
        check(it.kind == exp_kind, f"{wid} kind {it.kind!r} == {exp_kind!r} (DB assignment_type {t['type']!r})")

        # due: tz-aware, same instant as the DB epoch, and SCENARIO's wall clock at the printed offset.
        if it.due is None:
            out("FAIL", f"{wid} due is None (DB due {t['due']})")
        else:
            check(it.due.tzinfo is not None and it.due.utcoffset() is not None, f"{wid} due is tz-aware")
            check(int(it.due.timestamp()) == t["due"],
                  f"{wid} due instant {it.due.isoformat()} == DB epoch {t['due']} "
                  f"({datetime.fromtimestamp(t['due'], timezone.utc).isoformat()})")
            check(it.due.replace(tzinfo=None) == wall(due_s), f"{wid} due wall clock == SCENARIO {due_s}")
            if t["db_os_wall"][:16] != due_s:
                out("INFO", f"{wid} the DB container's OS tzdata (TZ=America/Vancouver) renders this instant as "
                            f"{t['db_os_wall']}, WeBWorK (its own Perl tz database) as {due_s}: "
                            "the two tz databases disagree; the adapter keeps WeBWorK's printed zone")
            os_off = datetime.fromtimestamp(t["due"], VAN).utcoffset()
            if os_off != it.due.utcoffset():
                out("INFO", f"{wid} WeBWorK printed offset {it.due.utcoffset()} but this machine's tzdata says "
                            f"{os_off} for America/Vancouver at that instant: the adapter kept the server's")

        # opens: WeBWorK shows a student the open date only while the set is not open yet.
        if t["open"] > now:
            if it.opens is None:
                out("FAIL", f"{wid} not open yet but opens is None (DB open {t['open']})")
            else:
                check(it.opens.utcoffset() is not None and int(it.opens.timestamp()) == t["open"],
                      f"{wid} opens {it.opens.isoformat()} == DB epoch {t['open']}")
                check(it.opens.replace(tzinfo=None) == wall(open_s), f"{wid} opens wall clock == SCENARIO {open_s}")
        else:
            check(it.opens is None, f"{wid} already open: opens is None (student can't see it)")
            out("INFO", f"{wid} open date {open_s} is not shown to the student once open (DB {t['open']})")

        # url: that set's own page, 200 for the student, not a login form or course home.
        exp_url = f"{course_url}/{set_id}"
        check(it.url.rstrip("/") == exp_url, f"{wid} url {it.url} is the set deep link {exp_url}")
        r = sess.get(it.url, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.select_one("#page-title")
        crumb = soup.select_one("ol.breadcrumb li.active")
        check(r.status_code == 200 and soup.find(id="login_form") is None
              and title is not None and " ".join(title.get_text().split()) == set_id
              and crumb is not None and crumb.get_text(strip=True) == set_id,
              f"{wid} url returns 200 for fstudent and is {set_id}'s own page")
        # links_out: SCENARIO gives WeBWorK sets no outbound links.
        check(it.links_out == (), f"{wid} links_out empty (SCENARIO has none for WeBWorK): {it.links_out}")
        check(all(urlsplit(u).netloc != urlsplit(it.url).netloc for u in it.links_out),
              f"{wid} links_out only other hosts")

    for i in snap.items:
        for f in ("due", "opens"):
            v = getattr(i, f)
            if v is not None and v.utcoffset() is None:
                out("FAIL", f"{i.source_id} {f} is naive")

    if args.save_fixtures:
        fx = ROOT / "fixtures" / "webwork"
        fx.mkdir(parents=True, exist_ok=True)
        manifest = {}
        for n, (url, code, final, text) in enumerate(rec.log):
            path = urlsplit(url).path.strip("/").replace("/", "__") or "root"
            name = f"{n:02d}_{re.sub(r'[^A-Za-z0-9_.-]', '_', path)}.html"
            (fx / name).write_text(text)
            manifest[url] = {"file": name, "status": code, "final_url": final}
        (fx / "manifest.json").write_text(json.dumps({"base": args.base, "responses": manifest}, indent=2))
        snapshot_io.save(snap, ROOT / "fixtures" / "snapshots" / "webwork.json")
        out("INFO", f"saved {len(manifest)} raw responses to {fx} and the snapshot to fixtures/snapshots/webwork.json")

    print(f"{'FAIL' if fails else 'PASS'} overall: {fails} failure(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
