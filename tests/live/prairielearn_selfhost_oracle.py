"""Integration oracle: run the REAL hub.prairielearn._run() against a
self-hosted PrairieLearn (official Docker image, dev mode) loaded with the
fake course in tests/live/prairielearn_testcourse/, and check what comes back
against what that course configures.

Opt-in and networked: NOT a pytest test (the filename doesn't match test_*.py).
See tests/live/README.md for starting the container.

    uv run python tests/live/prairielearn_selfhost_oracle.py [BASE_URL] [--conformance]

--conformance also runs tests/live/adapter_conformance.check on the adapter
output (ground truth for undated: listed assessments configured with no end).

BASE_URL defaults to $PL_SELFHOST_URL, then http://100.124.35.27:3002.
Exit status is non-zero if any check FAILs. INFO lines are findings about
real PrairieLearn behaviour.

No product code is changed: hub.prairielearn.BASE is monkeypatched here, and
requests.Session is wrapped in a tiny shim with the Playwright
APIRequestContext surface _run() uses (req.get(url) -> .status, .ok,
.text(), .headers).

Dev-mode auth: PrairieLearn in dev mode logs every request in automatically.
With no cookie you're the dev admin ("Dev User"); the cookie
`pl_test_user=test_student` makes you the built-in test student
(student@example.com). No real accounts or passwords are involved.
"""
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hub.prairielearn as pl  # noqa: E402
from hub.models import category_for  # noqa: E402
from tests.live import adapter_conformance  # noqa: E402

CONFORMANCE = "--conformance" in sys.argv[1:]
ARGS = [a for a in sys.argv[1:] if a != "--conformance"]
BASE = (ARGS[0] if ARGS else os.environ.get("PL_SELFHOST_URL", "http://100.124.35.27:3002")).rstrip("/")
VAN = ZoneInfo("America/Vancouver")  # the course instance's configured timezone, real tzdata

# What tests/live/prairielearn_testcourse configures. end = the 100%-credit
# deadline, local America/Vancouver time (None = no end date).
EXPECTED = [
    # title,                            group heading,      kind,         end (local)
    ("Past Due Homework",               "Homeworks",        "assignment", "2026-09-20T23:59:59"),  # legacy
    ("Due Soon Homework",               "Homeworks",        "assignment", "2026-09-29T23:59:59"),  # legacy
    ("After BC Clock Change Homework",  "Homeworks",        "assignment", "2026-11-15T23:59:59"),  # legacy
    ("January 2027 Homework",           "Homeworks",        "assignment", "2027-01-15T23:59:59"),  # legacy
    ("No End Date Practice",            "Homeworks",        "assignment", None),                   # legacy
    ("Not Yet Open Homework",           "Homeworks",        "assignment", "2026-10-22T23:59:59"),  # legacy, starts 10-15
    ("Timed Quiz",                      "Quizzes",          "quiz",       "2026-10-10T18:00:00"),  # legacy, type Exam
    ("Midterm Exam",                    "Exams",            "exam",       "2026-10-20T20:00:00"),  # legacy, type Exam
    ("Modern Due Soon With Late",       "Machine Problems", "assignment", "2026-10-02T23:59:59"),  # accessControl, 50% late tier
    ("Modern January 2027",             "Machine Problems", "assignment", "2027-01-15T23:59:59"),  # accessControl
    ("Modern Not Yet Released",         "Machine Problems", "assignment", "2026-10-22T23:59:59"),  # accessControl, release 10-15, listed
    ("Modern Past Due Practice",        "Machine Problems", "assignment", "2026-09-20T23:59:59"),  # accessControl, 0% practice after
    ("Modern No Due Date",              "Machine Problems", "assignment", None),                   # accessControl
]
# Legacy allowAccess assessments vanish for students when no rule matches "now".
LEGACY_WINDOW = {
    "Past Due Homework": ("2026-09-01T00:00:01", "2026-09-24T23:59:59"),  # 50% tier ends 09-24
    "Not Yet Open Homework": ("2026-10-15T00:00:01", "2026-10-22T23:59:59"),
}
# PrairieLearn itself doesn't show a student the due date for these.
NOT_RELEASED = {"Modern Not Yet Released": "2026-10-15T00:00:01"}
PAST_LAST_DEADLINE = {"Modern Past Due Practice"}
COURSE = ("FAKE 101", "Oracle Test Course", "2026 Winter Term 1")

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def info(msg):
    print(f"INFO  {msg}")


def local(s):
    return datetime.fromisoformat(s).replace(tzinfo=VAN) if s else None


class Resp:
    def __init__(self, r):
        self._r = r
        self.status = r.status_code
        self.ok = r.ok
        self.headers = dict(r.headers)

    def text(self):
        return self._r.text


class Req:
    """requests.Session posing as a Playwright APIRequestContext."""

    def __init__(self, student=True):
        self.s = requests.Session()
        if student:
            self.s.cookies.set("pl_test_user", "test_student")

    def get(self, url):
        return Resp(self.s.get(url, timeout=30))


def sync_and_enroll():
    """Dev-mode setup: 'Load from disk' (syncs /course), then open the course
    instance as the test student, which self-enrolls them."""
    admin = requests.Session()
    r = admin.get(f"{BASE}/pl/loadFromDisk", timeout=60)
    job, page = r.url, ""
    for _ in range(30):
        page = admin.get(job, timeout=30).text
        if "Success" in page or "Error" in page or "Failure" in page:
            break
        time.sleep(1)
    check("setup: Load from disk succeeded", "Success" in page, job)
    home = BeautifulSoup(admin.get(f"{BASE}/", timeout=30).text, "html.parser")
    ci = None
    for tr in home.select("tr"):
        if COURSE[0] in tr.get_text() and COURSE[2] in tr.get_text():
            a = tr.select_one("a[href^='/pl/course_instance/']")
            if a:
                ci = a["href"].split("/")[3]
    check("setup: fake course instance visible to dev user", ci is not None, f"course_instance id {ci}")
    if ci is None:
        return None
    r = Req().get(f"{BASE}/pl/course_instance/{ci}/assessments")
    check("setup: test student can open assessments page (self-enrolls)", r.status == 200, f"HTTP {r.status}")
    return ci


def main():
    print(f"PrairieLearn under test: {BASE}\n")
    ci = sync_and_enroll()
    if ci is None:
        return 1

    pl.BASE = BASE  # monkeypatch: the adapter builds every URL from this
    req = Req()
    try:
        courses, items = pl._run(req)
    except Exception as e:  # noqa: BLE001
        check("hub.prairielearn._run(req) runs", False, repr(e))
        return 1
    check("hub.prairielearn._run(req) runs", True, f"{len(courses)} course(s), {len(items)} item(s)")

    # --- course title / COURSE_TITLE ---------------------------------------
    raw_home = BeautifulSoup(req.get(f"{BASE}/").text(), "html.parser")
    a = raw_home.select_one(f"a[href='/pl/course_instance/{ci}']")
    info(f"home-page link text as the adapter sees it: {a.get_text(strip=True) if a else None!r} "
         f"(PL renders '<course name>: <course title>, <instance longName>')")
    fake = [c for c in courses if c.code == COURSE[0]]
    check("course: fake course returned", len(fake) == 1, str([c.code for c in courses]))
    if fake:
        c = fake[0]
        check("course: COURSE_TITLE parses code/title/term", (c.code, c.title, c.term) == COURSE,
              str((c.code, c.title, c.term)))
    for alt in ["FAKE 101:Oracle Test Course,2026W1", "FAKE 101:Oracle Test Course,Fall 2026"]:
        info(f"COURSE_TITLE on a non-UBC-style longName {alt!r}: "
             f"{'matches' if pl.COURSE_TITLE.match(alt) else 'NO MATCH -> raw text becomes Course.code, term empty'}")

    # --- raw student page: what PL shows vs what the adapter returns --------
    raw = BeautifulSoup(req.get(f"{BASE}/pl/course_instance/{ci}/assessments").text(), "html.parser")
    raw_titles = {r.select("td")[1].get_text(strip=True) for r in raw.select("table tbody tr") if not r.find("th")}
    abbrevs = set()
    for b in raw.select("button[data-bs-content]"):
        abbrevs |= set(re.findall(r"\(([A-Z]{2,5})\)", b["data-bs-content"]))
    check("tz: every abbreviation PL rendered is in TZ_OFFSET", abbrevs <= set(pl.TZ_OFFSET),
          f"rendered {sorted(abbrevs)}, map has {sorted(pl.TZ_OFFSET)}")

    by_title = {i.title: i for i in items if i.course == COURSE[0]}
    now = datetime.now(timezone.utc)

    for title, group, kind, end in EXPECTED:
        win = LEGACY_WINDOW.get(title)
        if win and not (local(win[0]) <= now <= local(win[1])):
            check(f"[{title}] absent from the student page too (PL hides it, not an adapter bug)",
                  title not in raw_titles and title not in by_title)
            info(f"[{title}] legacy allowAccess with no rule active now is not listed for students, "
                 f"so the adapter can't see it (rule window {win[0]}..{win[1]})")
            continue
        it = by_title.get(title)
        check(f"[{title}] appears", it is not None)
        if it is None:
            continue
        check(f"[{title}] source", it.source == "prairielearn", it.source)
        check(f"[{title}] kind/category from group '{group}'", (it.kind, it.category) == (kind, category_for(kind)),
              f"got {it.kind}/{it.category}, want {kind}/{category_for(kind)}")

        want = local(end)
        if title in NOT_RELEASED and now < local(NOT_RELEASED[title]):
            want = None
            info(f"[{title}] not released: PL shows only 'Available <time>, <weekday>, <month> <day>' (no year, "
                 f"no popover), so due=None (documented adapter limit); real due {end}")
        if title in PAST_LAST_DEADLINE and want and now > want:
            want = None
            info(f"[{title}] past its last deadline (0% practice after): PL shows no credit text and no popover, "
                 f"so due=None and the past-due date is lost; real due {end}")
        if it.due is not None:
            check(f"[{title}] due is tz-aware", it.due.utcoffset() is not None)
        ok = (it.due is None and want is None) or (it.due is not None and want is not None and it.due == want)
        check(f"[{title}] due == configured end (real tzdata)", ok,
              f"adapter {it.due.isoformat() if it.due else None}, want {want.isoformat() if want else None}"
              + (f" [{want.tzname()}]" if want else ""))

        check(f"[{title}] deep link absolute under BASE", it.url.startswith(BASE + "/pl/course_instance/"), repr(it.url))
        if it.url.startswith("http"):
            r = req.get(it.url)
            check(f"[{title}] deep link opens (200, shows title)", r.status == 200 and title in r.text(),
                  f"HTTP {r.status}")

    extra = set(by_title) - {t for t, *_ in EXPECTED}
    check("no unexpected items for the fake course", not extra, str(sorted(extra)))

    # Fixed PST/PDT map vs real tzdata (tzdata 2026c+: America/Vancouver stays
    # at -07 after 2026-11-01, abbreviated 'MST').
    for d in ["2026-11-15T23:59:59", "2027-01-15T23:59:59", "2027-07-15T12:00:00"]:
        z = local(d)
        info(f"real tzdata {d}: {z.tzname()} UTC{z.utcoffset().total_seconds() / 3600:+.0f}h | TZ_OFFSET gives "
             f"{z.tzname()} -> {pl.TZ_OFFSET.get(z.tzname(), 0):+d}h (unknown abbrev falls back to UTC+0)")

    if CONFORMANCE:
        print("\n--- adapter conformance")
        undated = sum(1 for t, _, _, end in EXPECTED if end is None and t in raw_titles)
        findings = adapter_conformance.check(courses, items, base=BASE, source="prairielearn", report_undated=undated)
        results.extend([False] * adapter_conformance.report(findings))

    fails = results.count(False)
    print(f"\n{len(results) - fails} PASS, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
