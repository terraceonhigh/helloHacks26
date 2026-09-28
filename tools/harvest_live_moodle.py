#!/usr/bin/env python3
"""LIVE ORACLE HARVEST: run MAIN's real hub.moodle adapter (imported
read-only from the oracle checkout, /sdcard/Projects/helloHacks26) against
the disposable self-hosted Moodle on humboldt (100.124.35.27:3004, see
tests/live/moodle_selfhost/README.md), record every raw HTTP response the
adapter actually consumed, and write a replayable golden.

Sibling of tools/harvest_live.py (canvas/prairielearn/webwork), written
separately per this task's own instructions rather than added to that file,
which is another agent's path. Same conventions throughout: no hangs (every
network call is timed out), secrets never printed/logged/committed, only
this script (and tools/harvest_oracle.py / tools/harvest_live.py, not
touched here) writes tests/oracle/.

    UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \\
        ~/.local/bin/uv run --no-sync --project /sdcard/Projects/helloHacks26 \\
        python /sdcard/Projects/lauds-cli/tools/harvest_live_moodle.py

Exits 0 on a successful live-verified capture, 1 if the server didn't answer
or the login/capture failed.
"""
import dataclasses
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

LAUDS_ROOT = Path(__file__).resolve().parents[1]            # /sdcard/Projects/lauds-cli
ORACLE_ROOT = Path("/sdcard/Projects/helloHacks26")          # read-only oracle checkout, per BRIEF.md
FIXTURES = LAUDS_ROOT / "tests" / "fixtures" / "moodle"
ORACLE_GOLDENS = LAUDS_ROOT / "tests" / "oracle" / "moodle"

sys.path.insert(0, str(ORACLE_ROOT))  # only to import hub.*; never write here
from hub import moodle as hub_moodle          # noqa: E402

HUMBOLDT = "100.124.35.27"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"terrace@{HUMBOLDT}"]
HTTP_TIMEOUT = 15  # seconds, every request in this file
BASE = f"http://{HUMBOLDT}:3004"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


# --- secrets: loaded over ssh straight into memory, never printed ----------

def ssh_grep_env(remote_file, keys):
    """Read only the named KEY= lines of a remote .env over ssh, into a dict.
    Never printed, logged, or returned in any exception text."""
    pattern = "|".join(f"^{k}=" for k in keys)
    out = subprocess.run(
        SSH + [f"timeout 10 grep -E '{pattern}' {remote_file}"],
        capture_output=True, text=True, timeout=20, check=True,
    ).stdout
    env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    missing = [k for k in keys if k not in env]
    if missing:
        raise RuntimeError(f"{remote_file}: missing keys {missing}")  # names only, never values
    return {k: env[k] for k in keys}


class SecretScrubber:
    """Redacts every literal secret value it was told about, plus Moodle's
    own CSRF-style sesskey/logintoken, from any text before it touches disk."""

    _PATTERNS = [
        re.compile(r'("sesskey"\s*:\s*")[^"]*(")'),
        re.compile(r'([?&]sesskey=)[^&"\']+'),
        re.compile(r'(name="logintoken"[^>]*value=")[^"]*(")'),
    ]

    def __init__(self):
        self._values = set()

    def learn(self, *values):
        for v in values:
            if v:
                self._values.add(v)

    def scrub(self, text):
        if text is None:
            return text
        for v in sorted(self._values, key=len, reverse=True):  # longest first, avoid partial shadowing
            text = text.replace(v, "REDACTED")
        for pat in self._PATTERNS:
            text = pat.sub(r"\1REDACTED\2" if pat.groups == 2 else r"\1REDACTED", text)
        return text


SCRUB = SecretScrubber()


# --- recording request shim (Playwright APIRequestContext surface) ---------
# hub.moodle's _sesskey/_ajax call req.get(url) / req.post(url, data=, headers=)
# and read r.status / r.ok / r.text() -- exactly requests.Response's shape
# once wrapped, same trick tools/harvest_live.py uses for canvas/webwork.

class Resp:
    def __init__(self, r):
        self.status = r.status_code
        self.ok = r.ok
        self.headers = {k.lower(): v for k, v in r.headers.items()}
        self._text = r.text

    def text(self):
        return self._text


def _slug(url, max_len=60):
    path = urlparse(url).path.strip("/") or "home"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_").lower()
    return slug[:max_len] or "home"


class RecordingReq:
    """Wraps a requests.Session as the `req` object hub.moodle's internals
    call .get()/.post() on, and tees every response it returns into
    `captured` for fixture-writing. Only the calls hub.moodle._run() itself
    issues go through this; the login POST is done separately, on the same
    session, and is never recorded (it's the one place a password appears)."""

    def __init__(self, session):
        self.s = session
        self.captured = []  # [(url, method, ext, raw text)]
        self._written = 0  # index of the next uncaptured-to-disk entry

    def get(self, url):
        r = self.s.get(url, timeout=HTTP_TIMEOUT)
        resp = Resp(r)
        if resp.ok:
            self.captured.append((url, "get", "html", resp._text))
        return resp

    def post(self, url, data=None, headers=None):
        r = self.s.post(url, data=data, headers=headers, timeout=HTTP_TIMEOUT)
        resp = Resp(r)
        if resp.ok:
            self.captured.append((url, "post", "json", resp._text))
        return resp

    def write_fixtures(self):
        """Write every response captured since the last call, and return
        just those paths (so a second golden's `inputs` doesn't re-list an
        earlier golden's fixtures)."""
        FIXTURES.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(self._written, len(self.captured)):
            url, method, ext, text = self.captured[i]
            name = f"live_{i:02d}_{method}_{_slug(url)}.{ext}"
            (FIXTURES / name).write_text(SCRUB.scrub(text))
            paths.append(f"moodle/{name}")
        self._written = len(self.captured)
        return paths


# --- dataclasses -> golden JSON ---------------------------------------------

def _jsonable(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple, list)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def record(obj):
    return _jsonable(dataclasses.asdict(obj))


def write_golden(case, *, inputs, oracle_call, now, extra, courses=None, items=None):
    output = {}
    if courses is not None:
        output["courses"] = [record(c) for c in courses]
    if items is not None:
        output["items"] = [record(i) for i in items]
    golden = {
        "adapter": "moodle", "case": case, "inputs": inputs, "oracle_call": oracle_call,
        "now": now, "extra": extra, "output": output,
    }
    ORACLE_GOLDENS.mkdir(parents=True, exist_ok=True)
    path = ORACLE_GOLDENS / f"live_{case}.json"
    path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
    return path


def reachable(url):
    try:
        requests.get(url, timeout=HTTP_TIMEOUT)
        return True
    except requests.RequestException as e:
        print(f"  not reachable: {e}")
        return False


def login_headless(session, base, user, password):
    """Fill and submit Moodle's own login form directly (username/password/
    logintoken CSRF field), the way a real student's browser would -- no
    Playwright needed here, same choice tools/harvest_live.py's WeBWorK
    harvester made, since hub.moodle only ever needs an authenticated
    requests-like session, not a live browser. Returns True once we're
    past /login (mirrors hub.site.login's own "logged in" check)."""
    r = session.get(f"{base}/login/index.php", timeout=HTTP_TIMEOUT)
    m = re.search(r'name="logintoken"\s+value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("no logintoken on the Moodle login page")
    token = m.group(1)
    r = session.post(f"{base}/login/index.php", data={
        "anchor": "", "logintoken": token, "username": user, "password": password,
    }, timeout=HTTP_TIMEOUT, allow_redirects=True)
    return "/login/index.php" not in urlparse(r.url).path


def harvest_moodle():
    print(f"== moodle ({BASE}) ==")
    if not reachable(f"{BASE}/login/index.php"):
        return {"adapter": "moodle", "grade": "n/a", "note": "server did not answer"}
    creds = ssh_grep_env("~/moodle/secrets.env", ["MOODLE_STUDENT_USER", "MOODLE_STUDENT_PASSWORD"])
    user, password = creds["MOODLE_STUDENT_USER"], creds["MOODLE_STUDENT_PASSWORD"]
    SCRUB.learn(user, password)

    session = requests.Session()
    if not login_headless(session, BASE, user, password):
        return {"adapter": "moodle", "grade": "n/a", "note": "login did not leave /login; not harvesting"}

    when = now_iso()
    req = RecordingReq(session)
    now = dt.datetime.now(dt.timezone.utc)
    start = int(now.timestamp() - 120 * 86400)
    end = int(now.timestamp() + 120 * 86400)

    # --- Golden 1: hub.moodle._run(req, base, start, end) exactly as main
    # ships it (the same call fetch() makes; only the *session* is obtained
    # differently here - see login_headless's docstring). This is a real,
    # live-verified divergence, not a harness bug: it raises on every real
    # Moodle site (see tests/live/moodle_selfhost/README.md, "Oracle bugs
    # found"), and fetch() swallows that into ([], []). Recorded as such
    # (empty output) rather than skipped, because that silent-failure
    # behaviour *is* main's real, current, ground-truth output.
    try:
        courses, items = hub_moodle._run(req, BASE, start, end)
    except Exception as e:
        print(f"  hub.moodle._run raised (expected - see README): {e!r}")
        courses, items = [], []
    print(f"  fetch()-equivalent: {len(courses)} course(s), {len(items)} item(s)")
    inputs = req.write_fixtures()
    golden1 = write_golden(
        "fake101", inputs=inputs,
        oracle_call="hub.moodle.fetch(base), i.e. the try/except around hub.moodle._run(req, base, start, end)",
        now=when, extra={
            "base": BASE, "start": start, "end": end,
            "note": ("Always empty on a real Moodle site: _run() batches "
                     "core_enrol_get_users_courses with the calendar call, "
                     "but that function has no 'ajax' => true in "
                     "lib/db/services.php, so lib/ajax/service.php aborts "
                     "the whole batch on it (see README's Oracle bugs found "
                     "#1) and fetch() swallows the resulting exception."),
        },
        courses=courses, items=items,
    )
    print(f"  golden: {golden1.relative_to(LAUDS_ROOT)}")

    # --- Golden 2: hub.moodle.to_item over a *single*, unbatched
    # core_calendar_get_action_events_by_timesort call with limitnum=50 (not
    # main's hardcoded 100 - see README's Oracle bugs found #2). This is
    # real data from the real function once routed around both bugs: solid
    # ground truth for to_item()'s field mapping, even though no code path
    # in hub/moodle.py reaches it this way today.
    sesskey = hub_moodle._sesskey(req, BASE)
    calendar_only = hub_moodle._ajax(req, BASE, sesskey, [
        {"methodname": "core_calendar_get_action_events_by_timesort",
         "args": {"timesortfrom": start, "timesortto": end, "limitnum": 50}},
    ])
    events = calendar_only[0].get("data", {}).get("events", [])
    cal_items = [hub_moodle.to_item(e) for e in events]
    print(f"  calendar-only (limitnum=50): {len(cal_items)} item(s)")
    inputs2 = req.write_fixtures()  # only the two new calls made since golden 1
    golden2 = write_golden(
        "fake101_calendar_only", inputs=inputs2,
        oracle_call=("hub.moodle.to_item over each event from a single, unbatched "
                     "core_calendar_get_action_events_by_timesort call (limitnum=50)"),
        now=now_iso(), extra={"base": BASE, "start": start, "end": end, "limitnum": 50},
        items=cal_items,  # no courses: core_enrol_get_users_courses never succeeds live (bug #1)
    )
    print(f"  golden: {golden2.relative_to(LAUDS_ROOT)}")

    grade = "live-verified" if cal_items else "n/a"
    return {"adapter": "moodle", "grade": grade,
            "note": (f"fetch()-as-shipped: 0 courses/0 items (real, reproducible bug - see README); "
                     f"to_item over a corrected single call: {len(cal_items)} items")}


def main():
    try:
        report = harvest_moodle()
    except Exception as e:  # a bad run must never hang or leave a partial golden
        print(f"  FAILED: {e!r}")
        report = {"adapter": "moodle", "grade": "n/a", "note": f"error: {e!r}"}
    print("\n--- summary ---")
    print(f"{report['adapter']:14} {report['grade']:14} {report['note']}")
    sys.exit(0 if report["grade"] == "live-verified" else 1)


if __name__ == "__main__":
    main()
