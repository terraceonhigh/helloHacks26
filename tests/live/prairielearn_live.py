#!/usr/bin/env python3
"""PrairieLearn three-way live check: oracle vs lauds vs the golden, all
against the SAME live self-hosted PrairieLearn on humboldt right now.

Not a pytest test (networked, filename doesn't match test_*.py - see
tests/live/README.md). BRIEF.md's no-hang rules apply: every request is
timed out and this script makes at most a handful of GETs against a
dev-mode, no-credentials instance (see harvest_live.py's own note on that).

Three comparisons, each independently meaningful:
1. **oracle-now vs golden** - re-running main's own hub.prairielearn._run
   against the live server right now still matches
   tests/oracle/prairielearn/live_selfhost.json (the golden hasn't gone
   stale; the course's fixture data hasn't moved).
2. **lauds-now vs golden** - assert_superset(golden, lauds' live output):
   the actual parity-to-superset acceptance test, but against a fresh live
   fetch instead of the frozen golden.
3. **oracle-now vs lauds-now** - the two adapters, hitting the exact same
   requests in the exact same run, must produce field-for-field identical
   Items/Courses (up to lauds' superset additions) - the strongest form of
   parity, immune to the golden itself ever drifting from either adapter.

    UV_PROJECT_ENVIRONMENT=/home/.venvs/lauds ~/.local/bin/uv run --no-sync \
        --with-requirements <(echo requests) \
        python tests/live/prairielearn_live.py
(needs `requests`; already a lauds dependency via lauds.session's
RequestsContext path, so a plain `uv run --no-sync python ...` from this
repo's own venv has it.)
"""
import json
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
ORACLE_ROOT = Path("/sdcard/Projects/helloHacks26")  # read-only, per BRIEF.md
HUMBOLDT = "100.124.35.27"
BASE = f"http://{HUMBOLDT}:3002"
CAMPUS_KEY = "prairielearn-selfhost"  # distinct from the real "prairielearn"/"prairielearn_ok" keys
HTTP_TIMEOUT = 15

sys.path.insert(0, str(REPO))  # this repo first, so its own tests/ package wins over the oracle's

from lauds.compat import bundle_to_main  # noqa: E402
from lauds.adapters import prairielearn as lauds_pl  # noqa: E402
from tests.parity.superset import assert_superset, ORACLE  # noqa: E402

sys.path.insert(0, str(ORACLE_ROOT))  # only to import hub.prairielearn, read-only, never written to


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
    hub.prairielearn and lauds.adapters.prairielearn's `req` expect."""

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


def _session():
    s = requests.Session()
    s.cookies.set("pl_test_user", "test_student")  # dev-mode only; no credentials at all
    return s


SKIP = 77  # distinct from 0 (BRIEF minor finding): "ran it, exit 0" must not also mean "skipped it"


def main():
    if not _reachable():
        print("PrairieLearn self-hosted server did not answer - skipping (n/a, not a failure).")
        return SKIP

    print(f"== oracle run ({BASE}) ==")
    from hub import prairielearn as oracle_pl  # noqa: E402  (deferred: only needed if reachable)
    oracle_courses, oracle_items = oracle_pl._run(_Req(_session()), CAMPUS_KEY, BASE)
    print(f"  {len(oracle_courses)} course(s), {len(oracle_items)} item(s)")

    print(f"== lauds run ({BASE}) ==")
    lauds_courses, lauds_items = lauds_pl._run(_Req(_session()), CAMPUS_KEY, BASE)
    print(f"  {len(lauds_courses)} course(s), {len(lauds_items)} item(s)")

    problems = []

    # 1. oracle-now vs golden
    golden_path = ORACLE / "prairielearn" / "live_selfhost.json"
    golden = json.loads(golden_path.read_text())
    oracle_now_main = bundle_to_main({"courses": oracle_courses, "items": oracle_items})
    for kind in ("courses", "items"):
        golden_keys = {tuple(r.get(k) for k in (("code", "section", "term") if kind == "courses" else ("source", "url")))
                       for r in golden["output"].get(kind, [])}
        now_keys = {tuple(r.get(k) for k in (("code", "section", "term") if kind == "courses" else ("source", "url")))
                    for r in oracle_now_main.get(kind, [])}
        if golden_keys != now_keys:
            problems.append(f"[1: oracle-now vs golden] {kind} keys differ: "
                            f"golden-only={golden_keys - now_keys} now-only={now_keys - golden_keys}")

    # 2. lauds-now vs golden (the actual acceptance test, against a live fetch)
    try:
        assert_superset(golden_path, {"courses": lauds_courses, "items": lauds_items})
        print("  [2: lauds-now vs golden] assert_superset: PASS")
    except AssertionError as e:
        problems.append(f"[2: lauds-now vs golden] {e}")

    # 3. oracle-now vs lauds-now, directly (no golden in between)
    lauds_now_main = bundle_to_main({"courses": lauds_courses, "items": lauds_items})
    for kind in ("courses", "items"):
        by_key = {}
        key_fields = ("code", "section", "term") if kind == "courses" else ("source", "url")
        for r in lauds_now_main.get(kind, []):
            by_key[tuple(r.get(k) for k in key_fields)] = r
        for o in oracle_now_main.get(kind, []):
            k = tuple(o.get(f) for f in key_fields)
            n = by_key.get(k)
            if n is None:
                problems.append(f"[3: oracle-now vs lauds-now] {kind} {k}: missing from lauds' live output")
                continue
            for field, ov in o.items():
                if ov not in (None, "", [], {}) and n.get(field) != ov:
                    problems.append(f"[3: oracle-now vs lauds-now] {kind} {k} field {field!r}: "
                                    f"oracle={ov!r} lauds={n.get(field)!r}")

    print()
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("All three comparisons agree: oracle-now == golden, lauds-now superset-matches golden, "
          "oracle-now == lauds-now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
