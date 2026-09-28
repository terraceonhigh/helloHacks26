#!/usr/bin/env python3
"""LIVE ORACLE HARVEST: run MAIN's real adapters (hub.canvas, hub.prairielearn,
hub.webwork) against last night's self-hosted Canvas/PrairieLearn/WeBWorK on
humboldt, record every raw HTTP response each adapter actually consumed, and
write replayable goldens.

See tests/live/README.md for how to run this and what it produces. Binding
rules (BRIEF.md, this repo's root): no hangs (every network call is timed
out), secrets never printed/logged/committed (loaded over ssh straight into
env vars and scrubbed out of anything written to disk), and only this script
(plus tools/harvest_oracle.py, not written here) writes tests/oracle/.

    UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \
        ~/.local/bin/uv run --no-sync --project /sdcard/Projects/helloHacks26 \
        python /sdcard/Projects/lauds-cli/tools/harvest_live.py [adapter ...]

adapter is one or more of: canvas prairielearn webwork (default: all three).
Exits 0 if every requested adapter that answered produced a golden; a server
that didn't answer is recorded and skipped, not a hard failure. Exits 1 only
if every requested adapter failed.
"""
import dataclasses
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

# --- fixed layout -----------------------------------------------------------

LAUDS_ROOT = Path(__file__).resolve().parents[1]           # /sdcard/Projects/lauds-cli
ORACLE_ROOT = Path("/sdcard/Projects/helloHacks26")         # read-only oracle checkout, per BRIEF.md
FIXTURES = LAUDS_ROOT / "tests" / "fixtures"
ORACLE_GOLDENS = LAUDS_ROOT / "tests" / "oracle"

sys.path.insert(0, str(ORACLE_ROOT))  # only to import hub.*; never write here
from hub import canvas as hub_canvas          # noqa: E402
from hub import prairielearn as hub_pl        # noqa: E402
from hub import webwork as hub_webwork        # noqa: E402

HUMBOLDT = "100.124.35.27"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"terrace@{HUMBOLDT}"]
HTTP_TIMEOUT = 15  # seconds, every request in this file


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
    """Redacts every literal secret value it was told about, plus generic
    CSRF/session-token patterns, from any text before it touches disk."""

    _PATTERNS = [
        re.compile(r'("csrfToken"\s*:\s*")[^"]*(")'),
        re.compile(r'(name="key"[^>]*value=")[^"]*(")'),
        re.compile(r'([?&;]key=)[^&"\']+'),
        re.compile(r'(name="otp_code"[^>]*value=")[^"]*(")'),
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
            if pat.groups == 2:
                text = pat.sub(r"\1REDACTED\2", text)
            else:
                text = pat.sub(r"\1REDACTED", text)
        return text


SCRUB = SecretScrubber()


# --- recording request shim (Playwright APIRequestContext surface) ---------

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
    """requests.Session posing as the Playwright request context hub.site's
    adapters call .get(url) on -- and, unlike the plain oracle scripts, tees
    every response it returns into `captured` for fixture-writing. Only GETs
    the *adapter itself* issues go through this; login is done separately
    and is never recorded (see harvest_* below)."""

    def __init__(self, session, ext):
        self.s = session
        self.ext = ext  # file extension for captured bodies, e.g. "json" or "html"
        self.captured = []  # [(url, path-within-tests/fixtures, raw text)]

    def get(self, url):
        r = self.s.get(url, timeout=HTTP_TIMEOUT)
        resp = Resp(r)
        if resp.ok:
            self.captured.append((url, resp._text))
        return resp

    def write_fixtures(self, adapter):
        out_dir = FIXTURES / adapter
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, (url, text) in enumerate(self.captured):
            name = f"live_{i:02d}_{_slug(url)}.{self.ext}"
            (out_dir / name).write_text(SCRUB.scrub(text))
            paths.append(f"{adapter}/{name}")
        return paths


# --- dataclasses -> golden JSON ---------------------------------------------

def _jsonable(value):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (set, frozenset, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def record(obj):
    return _jsonable(dataclasses.asdict(obj))


def write_golden(adapter, case, *, inputs, oracle_call, now, extra, courses=None, items=None,
                 textbooks=None, meetings=None):
    output = {}
    if courses is not None:
        output["courses"] = [record(c) for c in courses]
    if items is not None:
        output["items"] = [record(i) for i in items]
    if textbooks is not None:
        output["textbooks"] = [record(t) for t in textbooks]
    if meetings is not None:
        output["meetings"] = [record(m) for m in meetings]
    golden = {
        "adapter": adapter, "case": case, "inputs": inputs, "oracle_call": oracle_call,
        "now": now, "extra": extra, "output": output,
    }
    out_dir = ORACLE_GOLDENS / adapter
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"live_{case}.json"
    path.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
    return path


# --- per-adapter harvesters --------------------------------------------------

def reachable(url):
    try:
        requests.get(url, timeout=HTTP_TIMEOUT)
        return True
    except requests.RequestException as e:
        print(f"  not reachable: {e}")
        return False


def harvest_canvas():
    base = f"http://{HUMBOLDT}:3001"
    print(f"== canvas ({base}) ==")
    if not reachable(f"{base}/login/canvas"):
        return {"adapter": "canvas", "grade": "n/a", "note": "server did not answer"}
    creds = ssh_grep_env("~/canvas-lms/secrets.env", ["CANVAS_TOKEN"])
    token = creds["CANVAS_TOKEN"]
    SCRUB.learn(token)
    when = now_iso()
    hub_canvas.BASE = base  # monkeypatch only, no product-code change (same as the selfhost oracle script)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"
    req = RecordingReq(session, "json")
    start = dt.date.today() - dt.timedelta(days=120)
    end = dt.date.today() + dt.timedelta(days=120)
    courses, items = hub_canvas._run(req, start, end)
    print(f"  {len(courses)} course(s), {len(items)} item(s)")
    inputs = req.write_fixtures("canvas")
    golden = write_golden(
        "canvas", "selfhost", inputs=inputs,
        oracle_call="hub.canvas._run(req, start, end)", now=when,
        extra={"start": start.isoformat(), "end": end.isoformat(), "base": base},
        courses=courses, items=items,
    )
    print(f"  golden: {golden.relative_to(LAUDS_ROOT)}")
    return {"adapter": "canvas", "grade": "live-verified", "note": f"{len(courses)} courses, {len(items)} items"}


def harvest_prairielearn():
    base = f"http://{HUMBOLDT}:3002"
    print(f"== prairielearn ({base}) ==")
    if not reachable(f"{base}/"):
        return {"adapter": "prairielearn", "grade": "n/a", "note": "server did not answer"}
    # Dev-mode auth only: the pl_test_user cookie picks the built-in test
    # student. No account, password, or secret of any kind is involved (see
    # tests/live's oracle/selfhost-prairielearn branch README) -- confirmed
    # against this instance before writing this script.
    session = requests.Session()
    session.cookies.set("pl_test_user", "test_student")
    campus_key = "prairielearn-selfhost"  # distinct from the real "prairielearn"/"prairielearn_ok" keys
    when = now_iso()
    req = RecordingReq(session, "html")
    courses, items = hub_pl._run(req, campus_key, base)
    print(f"  {len(courses)} course(s), {len(items)} item(s)")
    inputs = req.write_fixtures("prairielearn")
    golden = write_golden(
        "prairielearn", "selfhost", inputs=inputs,
        oracle_call="hub.prairielearn._run(req, campus_key, base)", now=when,
        extra={"campus_key": campus_key, "base": base},
        courses=courses, items=items,
    )
    print(f"  golden: {golden.relative_to(LAUDS_ROOT)}")
    return {"adapter": "prairielearn", "grade": "live-verified",
            "note": f"{len(courses)} courses, {len(items)} items; no credentials needed (dev-mode cookie)"}


def totp(secret, t=None):
    """RFC 6238, SHA1, 6 digits, 30s step -- same formula WeBWorK's default
    TOTP step uses, keyed with the raw pre-provisioned secret string."""
    h = hmac.new(secret.encode(), struct.pack(">Q", int(t or time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6)


def harvest_webwork():
    course_id = "fake101"
    course_code = "FAKE101"
    base = f"http://{HUMBOLDT}:3003/webwork2/{course_id}"
    print(f"== webwork ({base}) ==")
    if not reachable(f"{base}/"):
        return {"adapter": "webwork", "grade": "n/a", "note": "server did not answer"}
    creds = ssh_grep_env("~/webwork/secrets.env", ["WW_STUDENT_USER", "WW_STUDENT_PASSWORD", "WW_STUDENT_OTP_SECRET"])
    user, password, otp_secret = creds["WW_STUDENT_USER"], creds["WW_STUDENT_PASSWORD"], creds["WW_STUDENT_OTP_SECRET"]
    SCRUB.learn(user, password, otp_secret)
    session = requests.Session()
    # Login itself is never recorded/written to disk (it's the one place a
    # password/OTP code appears at all) -- only the adapter's own GET(s),
    # made on this now-authenticated session, are captured below.
    r = session.post(f"{base}/", data={"user": user, "passwd": password}, timeout=HTTP_TIMEOUT)
    if 'name="otp_code"' in r.text:
        code = totp(otp_secret)
        SCRUB.learn(code)
        r = session.post(f"{base}/", data={"otp_code": code, "verify_otp": "Continue"}, timeout=HTTP_TIMEOUT)
    if 'id="set-list-container"' not in r.text:
        return {"adapter": "webwork", "grade": "n/a", "note": "login did not reach the set list; not harvesting"}
    when = now_iso()
    req = RecordingReq(session, "html")
    # hub/webwork.py exposes no _run(); its real entry point for a known
    # base+course_code is _problem_sets(), which calls to_item() over each
    # <li data-set-status> on the one page it fetches (module docstring:
    # the adapter never visits a set's own page, so due=None for
    # not-yet-open/past-due sets is the documented, correct behaviour, not
    # a gap in this harvest).
    items = hub_webwork._problem_sets(req, base, course_code)
    print(f"  {len(items)} item(s)")
    inputs = req.write_fixtures("webwork")
    golden = write_golden(
        "webwork", "selfhost", inputs=inputs,
        oracle_call="hub.webwork.to_item over each <li> from hub.webwork._problem_sets(req, base, course_code)",
        now=when, extra={"base": base, "course_code": course_code},
        items=items,  # no Course record: hub/webwork.py never produces one (see module docstring)
    )
    print(f"  golden: {golden.relative_to(LAUDS_ROOT)}")
    return {"adapter": "webwork", "grade": "live-verified", "note": f"{len(items)} items; TOTP login used"}


HARVESTERS = {"canvas": harvest_canvas, "prairielearn": harvest_prairielearn, "webwork": harvest_webwork}


def main():
    requested = [a for a in sys.argv[1:] if not a.startswith("-")] or list(HARVESTERS)
    unknown = [a for a in requested if a not in HARVESTERS]
    if unknown:
        sys.exit(f"unknown adapter(s) {unknown}; choose from {list(HARVESTERS)}")
    reports = []
    for name in requested:
        try:
            reports.append(HARVESTERS[name]())
        except Exception as e:  # one bad adapter must never stop the others
            print(f"  FAILED: {e!r}")
            reports.append({"adapter": name, "grade": "n/a", "note": f"error: {e!r}"})
    print("\n--- summary ---")
    for r in reports:
        print(f"{r['adapter']:14} {r['grade']:14} {r['note']}")
    sys.exit(0 if any(r["grade"] == "live-verified" for r in reports) else 1)


if __name__ == "__main__":
    main()
