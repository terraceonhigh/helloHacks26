#!/usr/bin/env python3
"""Canvas three-way live check: oracle vs lauds vs the golden, all against
the SAME live self-hosted Canvas on humboldt right now.

Not a pytest test (networked, filename doesn't match test_*.py - see
tests/live/README.md). BRIEF.md's no-hang rules apply: every request is
timed out, the ssh call for the secret is BatchMode+ConnectTimeout'd, and
this script makes at most a handful of GETs against a self-hosted instance
that's under real load right now - be gentle, it's a full fetch (courses +
planner/items + one assignments page per course), same as one real sync.

Three comparisons, each independently meaningful:
1. **oracle-now vs golden** - re-running main's own hub.canvas._run against
   the live server right now still matches
   tests/oracle/canvas/live_selfhost.json (the golden hasn't gone stale;
   humboldt's fixture data hasn't moved).
2. **lauds-now vs golden** - assert_superset(golden, lauds' live output):
   the actual parity-to-superset acceptance test, but against a fresh live
   fetch instead of the frozen golden.
3. **oracle-now vs lauds-now** - the two adapters, hitting the exact same
   requests in the exact same run, must produce field-for-field identical
   Courses/Items (up to lauds' superset additions) - the strongest form of
   parity, immune to the golden itself ever drifting from either adapter.

The Canvas student API token is read straight from humboldt's own secrets
file over ssh into this process's memory; it is never printed, logged, or
included in any exception message this script raises.

    UV_PROJECT_ENVIRONMENT=/home/.venvs/lauds ~/.local/bin/uv run --no-sync \
        python tests/live/canvas_live.py
(needs `requests`; already a lauds dependency, so a plain `uv run --no-sync
python ...` from this repo's own venv has it.)
"""
import datetime as dt
import subprocess
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
ORACLE_ROOT = Path("/sdcard/Projects/helloHacks26")  # read-only, per BRIEF.md
HUMBOLDT = "100.124.35.27"
BASE = f"http://{HUMBOLDT}:3001"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"terrace@{HUMBOLDT}"]
HTTP_TIMEOUT = 15
SSH_TIMEOUT = 20

sys.path.insert(0, str(REPO))  # this repo first, so its own tests/ package wins over the oracle's

from lauds.compat import bundle_to_main  # noqa: E402
from lauds.adapters import canvas as lauds_canvas  # noqa: E402
from tests.parity.superset import assert_superset, ORACLE  # noqa: E402

sys.path.insert(0, str(ORACLE_ROOT))  # only to import hub.canvas, read-only, never written to


def _reachable():
    try:
        requests.get(f"{BASE}/login/canvas", timeout=HTTP_TIMEOUT)
        return True
    except requests.RequestException as e:
        print(f"not reachable: {e}")
        return False


def _canvas_token():
    """CANVAS_TOKEN from humboldt's own secrets.env, over ssh, straight into
    memory - never printed, logged, or returned in any exception text."""
    out = subprocess.run(
        SSH + ["timeout 10 grep -E '^CANVAS_TOKEN=' ~/canvas-lms/secrets.env"],
        capture_output=True, text=True, timeout=SSH_TIMEOUT, check=True,
    ).stdout
    line = next((l for l in out.splitlines() if l.startswith("CANVAS_TOKEN=")), None)
    if line is None:
        raise RuntimeError("~/canvas-lms/secrets.env on humboldt has no CANVAS_TOKEN")
    return line.split("=", 1)[1]


class _TokenReq:
    """A bearer-token session in the `req.get(url)` shape both hub.canvas
    and lauds.adapters.canvas's `req` expect - built here (not from either
    adapter's own internal Bearer-request class) so this script exercises
    each adapter's real, independent HTTP path, not a shared helper."""

    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, url):
        r = self.session.get(url, timeout=HTTP_TIMEOUT, allow_redirects=False)
        return _Resp(r)


class _Resp:
    def __init__(self, r):
        self.status = r.status_code
        self.ok = r.ok
        self.headers = {k.lower(): v for k, v in r.headers.items()}
        self._text = r.text

    def text(self):
        return self._text


def main():
    if not _reachable():
        print("Canvas self-hosted server did not answer - skipping (n/a, not a failure).")
        return 0

    try:
        token = _canvas_token()
    except Exception as e:
        print(f"couldn't read CANVAS_TOKEN over ssh ({type(e).__name__}) - skipping (n/a, not a failure).")
        return 0

    start = dt.date.today() - dt.timedelta(days=120)
    end = dt.date.today() + dt.timedelta(days=120)

    print(f"== oracle run ({BASE}) ==")
    from hub import canvas as oracle_canvas  # noqa: E402  (deferred: only needed if reachable)
    saved_base = oracle_canvas.BASE
    oracle_canvas.BASE = BASE  # monkeypatch only, no product-code change (same as tools/harvest_live.py)
    try:
        oracle_courses, oracle_items = oracle_canvas._run(_TokenReq(token), start, end)
    finally:
        oracle_canvas.BASE = saved_base
    print(f"  {len(oracle_courses)} course(s), {len(oracle_items)} item(s)")

    print(f"== lauds run ({BASE}) ==")
    saved_base = lauds_canvas.BASE
    lauds_canvas.BASE = BASE
    try:
        lauds_bundle = lauds_canvas._run(_TokenReq(token), start, end)
    finally:
        lauds_canvas.BASE = saved_base
    print(f"  {len(lauds_bundle.courses)} course(s), {len(lauds_bundle.items)} item(s)")

    problems = []

    # 1. oracle-now vs golden
    golden_path = ORACLE / "canvas" / "live_selfhost.json"
    golden = json_load(golden_path)
    oracle_now_main = bundle_to_main({"courses": oracle_courses, "items": oracle_items})
    for kind in ("courses", "items"):
        key_fields = ("code", "section", "term") if kind == "courses" else ("source", "url")
        golden_keys = {tuple(r.get(k) for k in key_fields) for r in golden["output"].get(kind, [])}
        now_keys = {tuple(r.get(k) for k in key_fields) for r in oracle_now_main.get(kind, [])}
        if golden_keys != now_keys:
            problems.append(f"[1: oracle-now vs golden] {kind} keys differ: "
                            f"golden-only={golden_keys - now_keys} now-only={now_keys - golden_keys}")

    # 2. lauds-now vs golden (the actual acceptance test, against a live fetch)
    try:
        assert_superset(golden_path, lauds_bundle)
        print("  [2: lauds-now vs golden] assert_superset: PASS")
    except AssertionError as e:
        problems.append(f"[2: lauds-now vs golden] {e}")

    # 3. oracle-now vs lauds-now, directly (no golden in between)
    lauds_now_main = bundle_to_main(lauds_bundle)
    for kind in ("courses", "items"):
        key_fields = ("code", "section", "term") if kind == "courses" else ("source", "url")
        by_key = {tuple(r.get(k) for k in key_fields): r for r in lauds_now_main.get(kind, [])}
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


def json_load(path):
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
