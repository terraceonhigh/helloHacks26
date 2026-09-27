"""Live end-to-end oracle: fetch every configured source, fuse, compare to SCENARIO.

    uv run python oracles/e2e_live.py [--sources oracles/sources.toml] [--save DIR]

Fetches WeBWorK, PrairieLearn and Moodle live through their adapters (logins from
oracles/<p>/login.py), replays the [[snapshot]] entries (Canvas, synthetic), fuses,
and checks the result against SCENARIO.md's "Expected fused tracks" table with the
same checker as tests/test_e2e.py (tests/e2e_expected.py). Status is evaluated at
the fixed SCENARIO now (2026-09-27 12:00 PDT); the real-now status is printed too.

Exit 0 when exact; exit 1 on any mismatch or any failing source. Not collected by
pytest. Never prints secrets.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fusion import fuse as F  # noqa: E402
from fusion import run, snapshot_io  # noqa: E402
from tests.e2e_expected import NOW, check  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=str(ROOT / "oracles" / "sources.toml"))
    ap.add_argument("--save", metavar="DIR", help="also write each live Snapshot as DIR/<source>.json")
    a = ap.parse_args(argv)

    results = run.collect({"live": a.sources})
    failed = False
    for h in run.health(results):
        state = "ok" if h["ok"] else f"ERROR {h['error']}"
        print(f"SOURCE {h['source']:>13} {state}  origin={h['origin']}  "
              f"{h['courses']} courses, {h['observations']} observations")
        for n in h["notes"]:
            print(f"  note: {n}")
        failed |= not h["ok"]
    snaps = run.snapshots(results)
    if a.save:
        for s in snaps:
            snapshot_io.save(s, Path(a.save) / f"{s.source}.json")

    courses, tracks, warnings = F.fuse(snaps)
    real_now = datetime.now(timezone.utc).astimezone()
    print(f"\n{len(tracks)} tracks, {len(warnings)} warnings (status at SCENARIO now {NOW.isoformat()}; "
          f"real now {real_now.isoformat(timespec='minutes')})")
    for t in F.order(tracks, NOW, include_done=True):
        srcs = ",".join(sorted({m.source for m in t.members}))
        due = t.due.value.isoformat() if t.due else "-"
        print(f"  {t.id}  {F.course_name(t.course):18} {t.title.value:22} {due:26} "
              f"{F.status(t, NOW):9} (now: {F.status(t, real_now):9}) {srcs:28} "
              f"conflicts={len(t.conflicts)} -> {t.action_url}")
    for w in warnings:
        print(f"  WARNING {w}")

    errors = check(snaps, NOW, live=True)
    print()
    for e in errors:
        print(f"FAIL {e}")
    if failed:
        print("FAIL at least one source did not fetch")
    ok = not errors and not failed
    print("PASS e2e live: fused output matches SCENARIO exactly" if ok else f"FAIL e2e live: {len(errors)} mismatch(es)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
