"""Adapter conformance suite: rules every adapter's real output must follow.

Any provider oracle (tests/live/*_oracle.py) calls this on what the adapter
actually returned from a real server:

    from tests.live import adapter_conformance as ac
    findings = ac.check(courses, items, base=BASE, source="canvas", report_undated=3)
    ac.report(findings)   # prints FAIL/WARN/INFO lines, returns the FAIL count

Rules (each drawn from a bug a real server exposed; see AGENTS.md
"Jacky's standard"):

1. FAIL  every Item.due is tz-aware or None.
2. FAIL  url is non-empty, absolute, under `base` (or an `external_hosts`
         host), and has no doubled base ("http://hosthttp://host/...").
3. FAIL  (source, url) is unique across items, and every item's source is
         `source` - it's hub.db's upsert key, so duplicates silently merge.
4. FAIL  kind is non-empty and category == category_for(kind).
5. WARN  a due's UTC offset matches America/Vancouver's real offset at that
         instant (zoneinfo), catching fixed PST/PDT maps and unknown-abbrev
         -> UTC fallbacks. `utc_ok=True` accepts UTC instants (Canvas's API
         returns "...Z"); leave it False for sources that print local time.
6. WARN  if `report_undated` (the provider's ground-truth count of undated
         items) is given: were they kept or dropped?
7. WARN  every item's course matches a Course.code (exactly, or after
         hub.logic.normalise_course_code). FAIL if db.save into a temp
         sqlite raises or leaves items with no course (they never reach the
         UI). INFO the course-row count vs input course count: merging (e.g.
         lecture + lab) is Jacky's decided behaviour, so it's reported only.

Network-free itself; tests/test_adapter_conformance.py proves each rule
catches a known-bad input. CLI: `python tests/live/adapter_conformance.py
dump.json --base URL --source NAME` checks a JSON dump written by `dump()`.
"""
import json
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub import db  # noqa: E402
from hub.models import Course, Item, category_for  # noqa: E402

try:
    from hub.logic import normalise_course_code
except ImportError:  # a branch without it: exact-match only
    normalise_course_code = None

VAN = ZoneInfo("America/Vancouver")


@dataclass
class Finding:
    severity: str  # "FAIL" | "WARN" | "INFO"
    rule: int
    message: str
    item: str = ""  # the offending item's title, if any

    def __str__(self):
        return f"{self.severity}  [conformance {self.rule}] {self.message}" + (f"  -- {self.item!r}" if self.item else "")


def _course_key(code):
    if normalise_course_code is None or not code:
        return None
    faculty, number, _ = normalise_course_code(code)
    return (faculty, number) if faculty else None


def _h(td):
    return f"UTC{td.total_seconds() / 3600:+g}h"


def check(courses, items, *, base, source, report_undated=None, utc_ok=False, external_hosts=()):
    """Return a list of Findings for an adapter's (courses, items) output."""
    base = base.rstrip("/")
    out = []

    def f(sev, rule, msg, item=None):
        out.append(Finding(sev, rule, msg, item.title if item else ""))

    for it in items:
        # 1. tz-aware or None
        if it.due is not None and (not isinstance(it.due, datetime) or it.due.utcoffset() is None):
            f("FAIL", 1, f"naive due {it.due!r}", it)

        # 2. url absolute, under base, not doubled
        u = it.url or ""
        p = urlparse(u)
        if not u:
            f("FAIL", 2, "empty url", it)
        elif p.scheme not in ("http", "https") or not p.netloc:
            f("FAIL", 2, f"url not absolute: {u!r}", it)
        elif u.count("://") > 1:
            f("FAIL", 2, f"doubled base in url: {u!r}", it)
        elif not (u == base or u.startswith(base + "/") or p.hostname in external_hosts):
            f("FAIL", 2, f"url not under base {base!r}: {u!r}", it)

        # 3. source
        if it.source != source:
            f("FAIL", 3, f"source {it.source!r} != {source!r}", it)

        # 4. kind / category
        if not it.kind:
            f("FAIL", 4, "empty kind", it)
        elif it.category != category_for(it.kind):
            f("FAIL", 4, f"category {it.category!r} != category_for({it.kind!r}) = {category_for(it.kind)!r}", it)

        # 5. offset matches Vancouver's real offset at that instant
        if isinstance(it.due, datetime) and it.due.utcoffset() is not None:
            got, want = it.due.utcoffset(), it.due.astimezone(VAN).utcoffset()
            if got != want and not (utc_ok and got == timedelta(0)):
                f("WARN", 5, f"due {it.due.isoformat()} has offset {_h(got)} but America/Vancouver is {_h(want)} "
                             f"({it.due.astimezone(VAN).tzname()}) then - wall time off by {_h(got - want)}", it)

    # 3. (source, url) identity: hub.db's upsert key
    for (src, u), n in Counter((it.source, it.url) for it in items).items():
        if n > 1:
            titles = [it.title for it in items if (it.source, it.url) == (src, u)]
            f("FAIL", 3, f"{n} items share (source, url) = ({src!r}, {u!r}), one hub.db row: {titles}")

    # 6. undated kept or dropped
    if report_undated is not None:
        kept = sum(it.due is None for it in items)
        if kept < report_undated:
            f("WARN", 6, f"provider has {report_undated} undated item(s), adapter returned {kept} - "
                         f"{report_undated - kept} dropped")
        else:
            f("INFO", 6, f"provider has {report_undated} undated item(s), adapter returned {kept} undated - kept")

    # 7. course join
    codes = {c.code for c in courses}
    keys = {_course_key(c.code) for c in courses} - {None}
    for it in items:
        if it.course in codes:
            continue
        if _course_key(it.course) in keys:
            f("WARN", 7, f"course {it.course!r} matches a Course only after normalise_course_code "
                         "(db.save joins on exact text)", it)
        else:
            f("WARN", 7, f"course {it.course!r} matches no Course.code {sorted(codes)}", it)
    return out + _db_findings(courses, items)


def _db_findings(courses, items):
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "hub.db")
        try:
            db.save(conn, courses, items)
        except Exception as e:  # noqa: BLE001 - a crash in save is the finding
            conn.close()
            return [Finding("FAIL", 7, f"db.save raised {e!r}")]
        rows = conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        orphans = [r[0] for r in conn.execute("SELECT title FROM items WHERE course_id IS NULL")]
        conn.close()
    out = []
    if orphans:
        out.append(Finding("FAIL", 7, f"{len(orphans)} item(s) saved with no course (never reach upcoming()): "
                                      f"{orphans[:10]}{' ...' if len(orphans) > 10 else ''}"))
    merge = "" if rows == len(courses) else (" (merged)" if rows < len(courses) else " (split)")
    out.append(Finding("INFO", 7, f"db.save: {len(courses)} input course(s) -> {rows} course row(s){merge}; "
                                  f"{len(items)} input item(s) -> {n_items} item row(s)"))
    return out


def report(findings, out=print):
    """Print findings, FAILs first, and return how many FAILs there were."""
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    for x in sorted(findings, key=lambda x: (order[x.severity], x.rule)):
        out(str(x))
    c = Counter(x.severity for x in findings)
    out(f"conformance: {c['FAIL']} FAIL, {c['WARN']} WARN, {c['INFO']} INFO")
    return c["FAIL"]


def dump(courses, items, path):
    """Write adapter output as JSON for the CLI (dues as ISO strings)."""
    items = [{**asdict(i), "due": i.due.isoformat() if i.due else None} for i in items]
    Path(path).write_text(json.dumps({"courses": [asdict(c) for c in courses], "items": items}, indent=1))


def load(path):
    data = json.loads(Path(path).read_text())
    items = [Item(**{**i, "due": datetime.fromisoformat(i["due"]) if i["due"] else None}) for i in data["items"]]
    return [Course(**c) for c in data["courses"]], items


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Check a dumped adapter output against the conformance rules.")
    ap.add_argument("dump", help="JSON written by adapter_conformance.dump()")
    ap.add_argument("--base", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--undated", type=int, help="provider's ground-truth count of undated items")
    ap.add_argument("--utc-ok", action="store_true", help="accept UTC dues (sources that return instants)")
    a = ap.parse_args(argv)
    courses, items = load(a.dump)
    fails = report(check(courses, items, base=a.base, source=a.source, report_undated=a.undated, utc_ok=a.utc_ok))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
