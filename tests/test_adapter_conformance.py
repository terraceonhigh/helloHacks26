"""Each conformance rule catches the real-server bug it was written for.

Network-free: hand-built Course/Item lists, one known-bad thing each, plus
one clean input that must produce no FAIL/WARN.
"""
from dataclasses import replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from hub.models import Course, Item
from tests.live import adapter_conformance as ac

BASE = "http://host:3001"
VAN = ZoneInfo("America/Vancouver")
COURSES = [Course("CPSC 110", "101", "2026W1", "Computation"), Course("MATH 100", "101", "2026W1", "Calculus")]


def item(**kw):
    base = dict(course="CPSC 110", category="task", kind="assignment", title="A1",
                due=datetime(2026, 10, 15, 23, 59, tzinfo=VAN), url=f"{BASE}/courses/1/assignments/1",
                source="canvas")
    return Item(**{**base, **kw})


CLEAN = [
    item(),
    item(title="Q1", kind="quiz", category="deadline", url=f"{BASE}/courses/1/quizzes/2",
         due=datetime(2027, 1, 6, 23, 59, tzinfo=VAN)),
    item(title="R1", kind="reading", category="material", url=f"{BASE}/courses/2/pages/r1", course="MATH 100",
         due=None),
]


def bad(findings, severity=("FAIL", "WARN")):
    return [(f.severity, f.rule) for f in findings if f.severity in severity]


def test_clean_input_passes():
    findings = ac.check(COURSES, CLEAN, base=BASE, source="canvas", report_undated=1)
    assert bad(findings) == []
    assert ac.report(findings, out=lambda s: None) == 0


@pytest.mark.parametrize("name, items, want", [
    ("naive due", [item(due=datetime(2026, 10, 15, 23, 59))], ("FAIL", 1)),
    ("empty url (PrairieLearn unreleased)", [item(url="")], ("FAIL", 2)),
    ("relative url", [item(url="/courses/1/assignments/1")], ("FAIL", 2)),
    ("doubled base (Canvas calendar events)", [item(url=f"{BASE}{BASE}/calendar?event_id=1")], ("FAIL", 2)),
    ("url on another host", [item(url="https://evil.example/x")], ("FAIL", 2)),
    ("duplicate (source, url)", [item(), item(title="A2")], ("FAIL", 3)),
    ("wrong source", [item(source="prairielearn")], ("FAIL", 3)),
    ("wrong category", [item(kind="quiz", category="task")], ("FAIL", 4)),
    ("empty kind", [item(kind="", category="task")], ("FAIL", 4)),
    # Fixed PST map after tzdata's BC change: 2027-01-15 23:59 printed as PST
    # (-8) when Vancouver is really -7 then.
    ("fixed PST offset", [item(due=datetime.fromisoformat("2027-01-15T23:59:59-08:00"))], ("WARN", 5)),
    # Unknown "MST" abbreviation falling back to UTC.
    ("MST->UTC fallback", [item(due=datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc))], ("WARN", 5)),
    ("course matches nothing", [item(course="PHYS 999")], ("WARN", 7)),
])
def test_known_bad_is_caught(name, items, want):
    assert want in bad(ac.check(COURSES, items, base=BASE, source="canvas")), name


def test_utc_ok_accepts_utc_instants_but_still_checks_other_offsets():
    utc = item(due=datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc))
    assert bad(ac.check(COURSES, [utc], base=BASE, source="canvas", utc_ok=True)) == []
    pst = item(due=datetime.fromisoformat("2027-01-15T23:59:59-08:00"))
    assert ("WARN", 5) in bad(ac.check(COURSES, [pst], base=BASE, source="canvas", utc_ok=True))


def test_undated_dropped_vs_kept():
    dated = [i for i in CLEAN if i.due]
    assert ("WARN", 6) in bad(ac.check(COURSES, dated, base=BASE, source="canvas", report_undated=1))
    kept = ac.check(COURSES, CLEAN, base=BASE, source="canvas", report_undated=1)
    assert [f for f in kept if f.rule == 6 and f.severity == "INFO" and "kept" in f.message]


def test_orphan_items_fail_and_course_rows_are_reported():
    findings = ac.check(COURSES[:1], [item(course="MATH 100")], base=BASE, source="canvas")
    assert ("FAIL", 7) in bad(findings)
    # Two Course objects sharing a (code, term) collapse to one row: reported, not failed.
    lab = replace(COURSES[0], section="L1A", title="Computation Lab")
    merged = ac.check([COURSES[0], lab], [item()], base=BASE, source="canvas")
    assert bad(merged) == []
    assert any(f.severity == "INFO" and "2 input course(s) -> 1 course row(s) (merged)" in f.message for f in merged)


def test_normalised_course_match_is_a_warning_not_a_miss():
    findings = ac.check(COURSES, [item(course="CPSC_110")], base=BASE, source="canvas")
    assert any(f.rule == 7 and "only after normalise_course_code" in f.message for f in findings)


def test_dump_load_roundtrip(tmp_path):
    ac.dump(COURSES, CLEAN, tmp_path / "out.json")
    assert ac.main([str(tmp_path / "out.json"), "--base", BASE, "--source", "canvas"]) == 0
    ac.dump(COURSES, [item(url="")], tmp_path / "bad.json")
    assert ac.main([str(tmp_path / "bad.json"), "--base", BASE, "--source", "canvas"]) == 1
