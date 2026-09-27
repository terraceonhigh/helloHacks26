"""Integration oracle: a self-hosted WeBWorK 2.21 (official webwork2 Docker
build + MariaDB) with the FAKE course `fake101`, logged into as the fake
student through WeBWorK's normal login form.

Opt-in and networked: NOT a pytest test (the filename doesn't match test_*.py).
See tests/live/README.md for starting/stopping the server.

    uv run python tests/live/webwork_selfhost_oracle.py [BASE_URL] [--save-fixtures]

BASE_URL defaults to $WW_SELFHOST_URL, then http://100.124.35.27:3003/webwork2.

What it does:
  (a) logs in as the fake student: username/password form, then WeBWorK's
      default two-factor step (a TOTP code computed from the pre-provisioned
      test secret);
  (b) records the ground truth for every set from the student's set-list page
      (name, status, deep link) plus each set's own page, which states the due
      date even when the list doesn't (past-due sets);
  (c) if a WeBWorK adapter exists (hub/webwork*.py), runs its _run()/fetch()
      against the instance through a requests-backed shim of the Playwright
      APIRequestContext surface and compares; otherwise prints the ground
      truth and exits 0 with "no adapter yet".

Credentials: the fake course's test accounts live only in ~/webwork/secrets.env
on humboldt. They're read from $WW_STUDENT_USER / $WW_STUDENT_PASSWORD /
$WW_STUDENT_OTP_SECRET if set, else fetched over ssh; never printed.

--save-fixtures rewrites tests/fixtures/webwork/*.html (sanitized, fake data
only) for future unit tests.
"""
import hashlib
import hmac
import importlib
import os
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

args = [a for a in sys.argv[1:] if not a.startswith("--")]
SAVE_FIXTURES = "--save-fixtures" in sys.argv
BASE = (args[0] if args else os.environ.get("WW_SELFHOST_URL", "http://100.124.35.27:3003/webwork2")).rstrip("/")
COURSE_ID = "fake101"
COURSE = f"{BASE}/{COURSE_ID}"
FIXTURES = ROOT / "tests" / "fixtures" / "webwork"
VAN = ZoneInfo("America/Vancouver")  # the course's configured timezone (course.conf)

# What ~/webwork/setup_course.sh configures (course-local wall times,
# America/Vancouver). Set ids render with spaces for underscores.
EXPECTED = [
    # set id,                 open (local),          due (local)
    ("FAKE_HW1_Past_Due",     "2026-09-01T00:00:00", "2026-09-20T23:59:00"),
    ("FAKE_HW2_Due_Soon",     "2026-09-15T00:00:00", "2026-09-28T17:00:00"),
    ("FAKE_HW3_January_2027", "2026-09-15T00:00:00", "2027-01-15T23:59:00"),
    ("FAKE_HW4_Not_Yet_Open", "2026-10-15T00:00:00", "2026-10-22T23:59:00"),
    ("FAKE_HW5_Far_Future",   "2026-09-01T00:00:00", "2099-12-31T23:59:00"),  # WeBWorK has no "no due date"
]
# WeBWorK renders %Z abbreviations. Its Perl DateTime::TimeZone carries its own
# Olson copy (2.65 = tzdata 2025b in the image), so it still shows PST (-8) for
# BC winters even though tzdata 2026c keeps Vancouver at -7 ("MST").
ABBREV = {"PST": -8, "PDT": -7, "MST": -7, "UTC": 0, "GMT": 0}
DATE_RE = r"([A-Z][a-z]+ \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2} [AP]M) ([A-Z]{2,5})"

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))


def info(msg):
    print(f"INFO  {msg}")


def creds():
    keys = ("WW_STUDENT_USER", "WW_STUDENT_PASSWORD", "WW_STUDENT_OTP_SECRET")
    if all(os.environ.get(k) for k in keys):
        return {k: os.environ[k] for k in keys}
    out = subprocess.run(
        ["ssh", "-i", os.path.expanduser("~/.ssh/claude_bazzite"), "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=10", "humboldt", "timeout 10 grep -E '^WW_STUDENT_' webwork/secrets.env"],
        capture_output=True, text=True, timeout=30, check=True).stdout
    env = dict(line.split("=", 1) for line in out.split())
    return {k: env[k] for k in keys}


def totp(secret, t=None):
    """RFC 6238 SHA1 / 6 digits / 30 s, keyed with the raw secret string the
    way WeBWorK::Utils::TOTP does (base32 is only for the otpauth URL)."""
    h = hmac.new(secret.encode(), struct.pack(">Q", int(t or time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10**6)


def login(c):
    s = requests.Session()
    r = s.post(f"{COURSE}/", data={"user": c["WW_STUDENT_USER"], "passwd": c["WW_STUDENT_PASSWORD"]}, timeout=30)
    two_factor = 'name="otp_code"' in r.text
    if two_factor:
        r = s.post(f"{COURSE}/", data={"otp_code": totp(c["WW_STUDENT_OTP_SECRET"]), "verify_otp": "Continue"},
                   timeout=30)
    return s, r, two_factor


def parse_when(text):
    """'January 15, 2027, 11:59:00 PM PST' -> aware datetime at the offset the
    abbreviation states (what WeBWorK means), or None."""
    m = re.search(DATE_RE, text or "")
    if not m or m.group(2) not in ABBREV:
        return None
    naive = datetime.strptime(m.group(1), "%B %d, %Y, %I:%M:%S %p")
    return naive.replace(tzinfo=timezone(timedelta(hours=ABBREV[m.group(2)]), m.group(2)))


def ground_truth(s):
    html = s.get(f"{COURSE}/", timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    sets, pages = [], {}
    for li in soup.select("#set-list-container li[data-set-status]"):
        a = li.select_one("a.fw-bold")
        href = a["href"]
        set_id = href.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        url = urljoin(BASE + "/", href)
        list_text = " ".join(li.select("div.font-sm")[0].get_text(" ", strip=True).split())
        page = s.get(url, timeout=30)
        pages[set_id] = page.text
        body = " ".join(BeautifulSoup(page.text, "html.parser").get_text(" ", strip=True).split())
        close = re.search(r"will close on " + DATE_RE, body)
        opens = re.search(r"(?:opens on|Will open on) " + DATE_RE, list_text + " " + body)
        sets.append({
            "set_id": set_id,
            "name": a.get_text(strip=True),
            "status": li["data-set-status"],
            "list_text": list_text,
            "due_text": " ".join(close.groups()) if close else None,
            "due": parse_when(" ".join(close.groups())) if close else None,
            "list_due": parse_when(list_text) if "Due " in list_text else None,
            "open": parse_when(" ".join(opens.groups())) if opens else None,
            "url": url,
            "http": page.status_code,
        })
    return html, sets, pages


def sanitize(html):
    html = re.sub(r"(Page generated )[^<]+", r"\1<REDACTED>", html)
    html = re.sub(r'(name="key"[^>]*value=")[^"]*', r"\1REDACTED", html)
    html = re.sub(r"([?&;]key=)[^&\"']+", r"\1REDACTED", html)
    host = BASE.split("//", 1)[-1].split("/", 1)[0]
    return html.replace(host, "webwork.example.invalid")


class Resp:
    def __init__(self, r):
        self._r = r
        self.status = r.status_code
        self.ok = r.ok
        self.headers = dict(r.headers)
        self.url = r.url

    def text(self):
        return self._r.text


class Req:
    """A logged-in requests.Session posing as a Playwright APIRequestContext
    (same pattern as tests/live/prairielearn_selfhost_oracle.py)."""

    def __init__(self, session):
        self.s = session

    def get(self, url, **_):
        return Resp(self.s.get(url, timeout=30))


def find_adapter():
    for p in sorted((ROOT / "hub").glob("webwork*.py")):
        return importlib.import_module(f"hub.{p.stem}")
    return None


def run_adapter(mod, session, truth):
    """Best effort against an adapter whose API isn't written yet: point any
    BASE/COURSE constants at this instance, call _run(req) or fetch(req)."""
    if hasattr(mod, "BASE"):
        mod.BASE = BASE if str(mod.BASE).rstrip("/").endswith("webwork2") else BASE.rsplit("/webwork2", 1)[0]
    for name in ("COURSE", "COURSE_ID"):
        if hasattr(mod, name):
            setattr(mod, name, COURSE_ID)
    fn = getattr(mod, "_run", None) or getattr(mod, "fetch", None)
    if fn is None:
        check(f"{mod.__name__} exposes _run() or fetch()", False,
              str(sorted(n for n in dir(mod) if not n.startswith("__"))))
        return
    try:
        out = fn(Req(session))
    except Exception as e:  # report it, don't crash the oracle
        check(f"{mod.__name__}.{fn.__name__}(req) runs", False, repr(e))
        return
    courses, items = out if isinstance(out, tuple) and len(out) == 2 else ([], out)
    check(f"{mod.__name__}.{fn.__name__}(req) runs", True, f"{len(courses)} course(s), {len(items)} item(s)")
    by_title = {getattr(i, "title", None): i for i in items}
    for t in truth:
        it = by_title.get(t["name"]) or by_title.get(t["set_id"])
        check(f"[adapter {t['name']}] appears", it is not None)
        if it is None:
            continue
        due = getattr(it, "due", None)
        check(f"[adapter {t['name']}] due tz-aware", due is None or due.utcoffset() is not None)
        check(f"[adapter {t['name']}] due == WeBWorK's due instant", due == t["due"],
              f"adapter {due.isoformat() if due else None}, truth {t['due'].isoformat() if t['due'] else None}")
        url = getattr(it, "url", "") or ""
        check(f"[adapter {t['name']}] deep link", url.split("?")[0].rstrip("/") == t["url"].split("?")[0].rstrip("/"),
              f"{url!r} vs {t['url']!r}")
    extra = set(by_title) - {t["name"] for t in truth} - {t["set_id"] for t in truth}
    check("[adapter] no unexpected items", not extra, str(sorted(map(str, extra))))


def main():
    print(f"WeBWorK oracle against {COURSE}/")
    c = creds()
    s, r, two_factor = login(c)
    logged_in = 'id="set-list-container"' in r.text
    check("login as the fake student via the normal form", logged_in, f"HTTP {r.status_code}")
    info(f"two-factor step after the password: {'yes (WeBWorK default $twoFA{enabled} = 1)' if two_factor else 'no'}")
    if not logged_in:
        return 1
    ver = re.search(r"ww_version: ([\d.]+) \| pg_version ([\d.]+)", r.text)
    info(f"server reports ww_version {ver.group(1)}, pg_version {ver.group(2)}" if ver else "no version footer")

    html, truth, pages = ground_truth(s)
    now = datetime.now(timezone.utc)

    print("\nGround truth (student's set list + each set page):")
    print(f"  {'set':<22} {'status':<9} {'due, as WeBWorK states it':<36} {'due UTC':<18} deep link")
    for t in truth:
        du = f"{t['due'].astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}" if t["due"] else "-"
        print(f"  {t['name']:<22} {t['status']:<9} {t['due_text'] or '-':<36} {du:<18} {t['url']}")
        print(f"  {'':<22} list says: {t['list_text']!r}")
    print()

    got = {t["set_id"]: t for t in truth}
    check("all 5 fake sets listed for the student", sorted(got) == sorted(e[0] for e in EXPECTED), str(sorted(got)))
    for set_id, open_s, due_s in EXPECTED:
        t = got.get(set_id)
        if not t:
            continue
        open_wall, due_wall = datetime.fromisoformat(open_s), datetime.fromisoformat(due_s)
        check(f"[{set_id}] name renders the id with spaces", t["name"] == set_id.replace("_", " "), t["name"])
        check(f"[{set_id}] deep link opens (200)", t["http"] == 200, f"HTTP {t['http']}")
        check(f"[{set_id}] due found on the set page, tz-aware", t["due"] is not None, repr(t["due_text"]))
        if t["due"] is None:
            continue
        check(f"[{set_id}] due wall time == configured {due_s}", t["due"].replace(tzinfo=None) == due_wall,
              t["due_text"])
        if t["list_due"] is not None:
            check(f"[{set_id}] list-page due == set-page due", t["list_due"] == t["due"], t["list_text"])
        real = due_wall.replace(tzinfo=VAN)
        if real.utcoffset() != t["due"].utcoffset():
            info(f"[{set_id}] WeBWorK: {t['due_text']} = {t['due'].astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}; "
                 f"this machine's tzdata puts {due_s} America/Vancouver at "
                 f"UTC{real.utcoffset().total_seconds() / 3600:+.0f}h ({real.tzname()}) = "
                 f"{real.astimezone(timezone.utc):%Y-%m-%dT%H:%MZ}. The server's instant is what the student "
                 f"is held to, so it's the truth an adapter must return.")

        opened = now >= (t["open"] or open_wall.replace(tzinfo=VAN))
        want = "not-open" if not opened else ("past-due" if now > t["due"] else "open")
        check(f"[{set_id}] status '{want}' at {now:%Y-%m-%dT%H:%MZ}", t["status"] == want, t["status"])
        if set_id == "FAKE_HW2_Due_Soon":
            left = t["due"] - now
            if timedelta(0) < left <= timedelta(hours=48):
                check(f"[{set_id}] due within 48h", True, str(left).split(".")[0])
            else:
                info(f"[{set_id}] not within 48h of now any more ({str(left).split('.')[0]}); it was at setup")
        if set_id == "FAKE_HW3_January_2027":
            check(f"[{set_id}] due after 2027-01-06", t["due"] > datetime(2027, 1, 6, tzinfo=VAN))
        if t["status"] == "not-open":
            check(f"[{set_id}] open date on the list == configured {open_s}",
                  t["open"] is not None and t["open"].replace(tzinfo=None) == open_wall, t["list_text"])
        if t["status"] == "past-due":
            info(f"[{set_id}] past due: the set list shows only {t['list_text']!r} (no date); "
                 f"the due date is only on the set page")

    # A problem in an open set renders (OPL: Library/Rochester/set0/prob1.pg).
    p = s.get(f"{COURSE}/FAKE_HW2_Due_Soon/1/", timeout=30)
    check("problem 1 of an open set renders", p.status_code == 200 and "Evaluate the expression" in p.text,
          f"HTTP {p.status_code}")

    if SAVE_FIXTURES:
        assert c["WW_STUDENT_USER"] == "fakestudent", "fixtures are only written for the fake student"
        FIXTURES.mkdir(parents=True, exist_ok=True)
        (FIXTURES / "set_list_fake101.html").write_text(sanitize(html))
        (FIXTURES / "set_FAKE_HW1_Past_Due.html").write_text(sanitize(pages["FAKE_HW1_Past_Due"]))
        info(f"fixtures written to {FIXTURES.relative_to(ROOT)}/")

    mod = find_adapter()
    if mod is None:
        info("no adapter yet (no hub/webwork*.py in this checkout); ground truth above")
    else:
        info(f"adapter found: {mod.__name__}")
        run_adapter(mod, s, truth)

    fails = results.count(False)
    print(f"\n{len(results) - fails} PASS, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
