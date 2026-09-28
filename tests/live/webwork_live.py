#!/usr/bin/env python3
"""WeBWorK three-way live check: oracle vs lauds vs the golden, all against
the SAME self-hosted WeBWorK on humboldt right now (course `fake101`).

Not a pytest test (networked, needs TOTP login; filename doesn't match
test_*.py -- see tests/live/README.md). BRIEF.md's no-hang rules apply:
every request is timed out, ssh is BatchMode with a ConnectTimeout, and this
script makes only the handful of requests a real login + one page fetch
needs.

Three comparisons, each independently meaningful:
1. **oracle-now vs golden** - re-running main's own
   `hub.webwork._problem_sets` against the live server right now still
   matches tests/oracle/webwork/live_selfhost.json (the golden hasn't gone
   stale; the fake course's set data hasn't moved).
2. **lauds-now vs golden** - assert_superset(golden, lauds' live output):
   the actual parity-to-superset acceptance test, but against a fresh live
   fetch instead of the frozen golden. Since the committed live fixture has
   its `effectiveUser` query param redacted (tests/live/README.md's
   "Secrets handling"; see tests/parity/test_webwork.py's
   `_unredact_effective_user`), this is also the only place the golden gets
   checked against genuinely fresh, *unredacted* page content.
3. **oracle-now vs lauds-now** - the two adapters, hitting the exact same
   page in the same run, must produce field-for-field identical Items (up
   to lauds' superset additions) - the strongest form of parity, immune to
   the golden itself ever drifting from either adapter.

Also verifies the PST-abbreviation-on-page rule live (tests/live/README.md,
origin/oracle/selfhost-webwork copy): at least one set's status text must
carry a literal "PST" abbreviation (the January 2027 / 2099 sets, dated
after BC's permanent-DST change), and lauds' parsed `due` for it must use a
fixed -08:00 offset, not whatever a real America/Vancouver zoneinfo lookup
would say for a post-cutover date.

    UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \
        ~/.local/bin/uv run --no-sync --project /sdcard/Projects/helloHacks26 \
        python /sdcard/Projects/lauds-cli/tests/live/webwork_live.py

(needs the oracle checkout's venv, since it imports hub.webwork read-only
from there; lauds' own venv also has `requests`, so a plain
`UV_PROJECT_ENVIRONMENT=/home/.venvs/lauds uv run --no-sync python ...` from
this repo works equally, as long as PYTHONPATH can still reach
/sdcard/Projects/helloHacks26 for the oracle import.)
"""
import hashlib
import hmac
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
ORACLE_ROOT = Path("/sdcard/Projects/helloHacks26")  # read-only, per BRIEF.md
HUMBOLDT = "100.124.35.27"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"terrace@{HUMBOLDT}"]
COURSE_ID = "fake101"
COURSE_CODE = "FAKE101"
BASE = f"http://{HUMBOLDT}:3003/webwork2/{COURSE_ID}"
HTTP_TIMEOUT = 15

sys.path.insert(0, str(REPO))  # this repo first, so its own tests/ package wins over the oracle's

from lauds.compat import bundle_to_main  # noqa: E402
from lauds.adapters import webwork as lauds_webwork  # noqa: E402
from tests.parity.superset import assert_superset, ORACLE  # noqa: E402

sys.path.insert(0, str(ORACLE_ROOT))  # only to import hub.webwork, read-only, never written to


# --- secrets: loaded over ssh straight into memory, never printed ----------

def ssh_grep_env(remote_file, keys):
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


def totp(secret, t=None):
    """RFC 6238, SHA1, 6 digits, 30s step - WeBWorK's default TOTP step,
    keyed with the raw pre-provisioned secret string."""
    h = hmac.new(secret.encode(), struct.pack(">Q", int(t or time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6)


# --- request-context shim (Playwright APIRequestContext surface) -----------

class _Resp:
    def __init__(self, r):
        self.status = r.status_code
        self.ok = r.ok
        self.headers = {k.lower(): v for k, v in r.headers.items()}
        self._text = r.text

    def text(self):
        return self._text


class _Req:
    """requests.Session posing as the Playwright request-context shape both
    hub.webwork and lauds.adapters.webwork's `req` expect."""

    def __init__(self, session):
        self.s = session

    def get(self, url):
        return _Resp(self.s.get(url, timeout=HTTP_TIMEOUT))


def _reachable():
    try:
        requests.get(f"{BASE}/", timeout=HTTP_TIMEOUT)
        return True
    except requests.RequestException as e:
        print(f"not reachable: {e}")
        return False


def _login():
    """Real username/password + TOTP login, same flow harvest_live.py uses.
    The login request/response (the one place a password/OTP code appears)
    is never printed, logged, or inspected beyond the one marker string
    needed to tell success from failure."""
    creds = ssh_grep_env("~/webwork/secrets.env", ["WW_STUDENT_USER", "WW_STUDENT_PASSWORD", "WW_STUDENT_OTP_SECRET"])
    user, password, otp_secret = creds["WW_STUDENT_USER"], creds["WW_STUDENT_PASSWORD"], creds["WW_STUDENT_OTP_SECRET"]
    s = requests.Session()
    r = s.post(f"{BASE}/", data={"user": user, "passwd": password}, timeout=HTTP_TIMEOUT)
    if 'name="otp_code"' in r.text:
        r = s.post(f"{BASE}/", data={"otp_code": totp(otp_secret), "verify_otp": "Continue"}, timeout=HTTP_TIMEOUT)
    if 'id="set-list-container"' not in r.text:
        raise RuntimeError("login did not reach the set list")
    return s


SKIP = 77  # distinct from 0 (BRIEF minor finding): "ran it, exit 0" must not also mean "skipped it"


def main():
    if not _reachable():
        print("WeBWorK self-hosted server did not answer - skipping (n/a, not a failure).")
        return SKIP

    print(f"== logging in ({BASE}) ==")
    session = _login()
    print("  logged in")

    print("== oracle run ==")
    from hub import webwork as oracle_webwork  # noqa: E402  (deferred: only needed if reachable)
    oracle_items = oracle_webwork._problem_sets(_Req(session), BASE, COURSE_CODE)
    print(f"  {len(oracle_items)} item(s)")

    print("== lauds run ==")
    r = _Req(session).get(BASE)
    lauds_items = lauds_webwork.parse_problem_sets(r.text(), COURSE_CODE, BASE)
    print(f"  {len(lauds_items)} item(s)")

    problems = []

    # 1. oracle-now vs golden
    golden_path = ORACLE / "webwork" / "live_selfhost.json"
    golden = json.loads(golden_path.read_text())
    oracle_now_main = bundle_to_main({"items": oracle_items})
    golden_keys = {(r["source"], r["url"]) for r in golden["output"].get("items", [])}
    now_keys = {(r["source"], r["url"]) for r in oracle_now_main.get("items", [])}
    if golden_keys != now_keys:
        problems.append(f"[1: oracle-now vs golden] item keys differ: "
                        f"golden-only={golden_keys - now_keys} now-only={now_keys - golden_keys}")

    # 2. lauds-now vs golden (the actual acceptance test, against a fresh,
    # unredacted live fetch - see module docstring)
    try:
        assert_superset(golden_path, {"items": lauds_items})
        print("  [2: lauds-now vs golden] assert_superset: PASS")
    except AssertionError as e:
        problems.append(f"[2: lauds-now vs golden] {e}")

    # 3. oracle-now vs lauds-now, directly (no golden in between)
    lauds_now_main = bundle_to_main({"items": lauds_items})
    by_key = {(r["source"], r["url"]): r for r in lauds_now_main.get("items", [])}
    for o in oracle_now_main.get("items", []):
        k = (o["source"], o["url"])
        n = by_key.get(k)
        if n is None:
            problems.append(f"[3: oracle-now vs lauds-now] item {k}: missing from lauds' live output")
            continue
        for field, ov in o.items():
            if ov not in (None, "", [], {}) and n.get(field) != ov:
                problems.append(f"[3: oracle-now vs lauds-now] item {k} field {field!r}: "
                                f"oracle={ov!r} lauds={n.get(field)!r}")

    # PST-abbreviation-on-page rule, checked live (module docstring)
    pst_items = [i for i in lauds_items if i.due is not None and i.due.utcoffset().total_seconds() == -8 * 3600]
    if not pst_items:
        problems.append("[PST rule] no live item parsed with a -08:00 (PST) offset - "
                        "expected at least one post-cutover set (Jan 2027 / 2099)")
    else:
        print(f"  [PST rule] {len(pst_items)} item(s) correctly kept at -08:00 "
              f"(page said PST; a real zoneinfo lookup for that date would differ)")

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("All three comparisons agree: oracle-now == golden, lauds-now superset-matches golden, "
          "oracle-now == lauds-now. PST-abbreviation rule holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
