"""End to end: the fused output of SCENARIO.md is EXACTLY the expected table.

Input is fixtures/snapshots/*.json: real captures from the live WeBWorK,
PrairieLearn and Moodle oracles (written by `oracles/<p>_oracle.py --save-fixtures`)
plus the SYNTHETIC Canvas snapshot (oracles/canvas_fixture_snapshot.py). Nothing
here is built by hand: every observation came out of an adapter.

The expected table lives in tests/e2e_expected.py, shared with oracles/e2e_live.py.
Network-free.
"""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fusion import fuse as F
from fusion import run
from tests.e2e_expected import (CV, DUE, EXPECTED, NOW, PDT, PL, PLATFORM_EXTRAS, PST, check,
                                check_row, match_ids)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "fixtures" / "snapshots"


@pytest.fixture(scope="module")
def fused():
    results = run.collect({"snapshots": SNAPSHOTS})
    assert [r.error for r in results] == [None] * len(results), run.health(results)
    snaps = run.snapshots(results)
    assert sorted(s.source for s in snaps) == ["canvas", "moodle", "prairielearn", "webwork"]
    courses, tracks, warnings = F.fuse(snaps)
    mapping, _, _ = F.resolve_courses(snaps)
    return snaps, courses, tracks, warnings, mapping


@pytest.fixture(scope="module")
def ids(fused):
    """SCENARIO id <-> (source, source_id), each mapped to exactly one real observation.
    Matched by content (source, course, title), because Moodle cmids and PL
    assessment ids are assigned by the servers at seed time."""
    snaps, _, _, _, mapping = fused
    obs, errors = match_ids(snaps, mapping)
    assert errors == []
    return {k: (o.source, o.source_id) for k, o in obs.items()}, obs


def test_every_observation_is_a_scenario_item_or_a_listed_extra(fused, ids):
    snaps = fused[0]
    sid, _ = ids
    known = set(sid.values())
    all_obs = [(o.source, o.source_id) for s in snaps for o in s.items]
    extras = [o for o in all_obs if o not in known]
    assert sorted(extras) == sorted(PLATFORM_EXTRAS), f"unlisted platform observations: {extras}"
    assert len(all_obs) == 19 + len(PLATFORM_EXTRAS)
    assert len(set(all_obs)) == len(all_obs)


def test_observation_dues_match_scenario(ids):
    _, obs = ids
    for name, want in DUE.items():
        got = obs[name].due
        assert got == want, f"{name}: {got} != {want}"
        if got is not None:
            assert got.utcoffset() is not None
    # HW9 keeps WeBWorK's own printed zone, not a re-derived one
    assert obs["W3"].due.utcoffset() == timedelta(hours=-8)


def test_not_open_items_carry_opens(ids):
    _, obs = ids
    assert obs["W3"].opens == datetime(2026, 12, 1, 0, 0, tzinfo=PST)
    assert obs["W4"].opens == datetime(2026, 10, 10, 0, 0, tzinfo=PDT)
    assert obs["P4"].opens == datetime(2026, 10, 20, 0, 0, tzinfo=PDT)


def test_exactly_14_tracks_no_warnings(fused):
    _, _, tracks, warnings, _ = fused
    assert len(tracks) == 14
    assert warnings == []
    assert all(t.warnings == [] for t in tracks)


def test_courses_resolve(fused):
    _, courses, _, _, _ = fused
    got = {F.course_name(c.key): sorted((l["source"], l["label"]) for l in c.labels) for c in courses}
    assert got == {
        "CPSC 121 / 2026W1": [("canvas", "CPSC_121_101_2026W1"), ("moodle", "CPSC121-101-2026W1"),
                              ("prairielearn", "CPSC 121, 2026W1")],
        "MATH 100 / 2026W1": [("moodle", "MATH100-2026W1"), ("webwork", "math100_2026w1")],
        "ENGL 110 / 2026W1": [("moodle", "ENGL110-001-2026W1")],
    }


def _row_id(row):
    return f"{row[0]} {row[1]}"


@pytest.mark.parametrize("row", EXPECTED, ids=_row_id)
def test_expected_track(row, fused, ids):
    """members, due + its authority, conflicts, every evidence edge and link direction,
    action_url and status at NOW, for one row of SCENARIO's table."""
    _, _, tracks, _, _ = fused
    assert check_row(row, tracks, ids[1], NOW) == []


def test_whole_table_exact(fused):
    """The same checker oracles/e2e_live.py runs: counts, extras, dues, all rows."""
    assert check(fused[0], NOW) == []


def test_scenario_traps(fused, ids):
    """The rows SCENARIO calls out as must-NOT-merge stay apart."""
    _, _, tracks, _, _ = fused
    sid, _ = ids
    track_of = {(m.source, m.source_id): t.id for t in tracks for m in t.members}
    assert track_of[sid["M4"]] != track_of[sid["M6"]]      # same title+due, different courses
    assert track_of[sid["M8"]] != track_of[sid["P3"]]      # Quiz 3 vs Quiz 2, same due
    assert track_of[sid["C2"]] != track_of[sid["P1"]]


def test_quiz1_kind_and_due_come_from_pl(fused, ids):
    _, _, tracks, _, _ = fused
    sid, _ = ids
    (t,) = [t for t in tracks if any((m.source, m.source_id) == sid["P1"] for m in t.members)]
    assert t.kind.value == "quiz" and (t.kind.source, t.kind.source_id) == sid["P1"]
    # M5 has no due (forgotten); C1's 23:59:59 is within the 5 min tolerance: no conflict
    assert t.conflicts == []
    assert t.links == {"canvas": f"{CV}/courses/4201/assignments/51001",
                       "moodle": ids[1]["M5"].url, "prairielearn": f"{PL}/assessment/3/"}


def test_lab4_deviation_is_surfaced_in_notes(fused):
    snaps = fused[0]
    (pl,) = [s for s in snaps if s.source == "prairielearn"]
    assert any("Lab 4" in n and "assessments page" in n for n in pl.notes)


def test_order_at_now(fused):
    _, _, tracks, _, _ = fused
    got = [(F.course_name(t.course).split(" /")[0], t.title.value) for t in F.order(tracks, NOW)]
    assert got == [
        ("MATH 100", "HW1"),                    # overdue first
        ("MATH 100", "HW2"),
        ("CPSC 121", "Tutorial 2 worksheet"),
        ("CPSC 121", "Quiz 1"),
        ("CPSC 121", "Problem Set 3"),
        ("ENGL 110", "Assignment 1"),           # tie on due: course order CPSC < ENGL < MATH
        ("MATH 100", "Assignment 1"),
        ("MATH 100", "Midterm 1"),
        ("CPSC 121", "Quiz 2"),
        ("CPSC 121", "Quiz 3"),
        ("MATH 100", "HW3"),
        ("CPSC 121", "Lab 4"),
        ("MATH 100", "HW9"),
        ("ENGL 110", "Reading: Chapter 4"),     # undated last
    ]


def test_sources_toml_mixes_live_and_snapshot_entries(tmp_path):
    """[[snapshot]] entries replay a saved file next to live [[source]]s (Canvas here)."""
    toml = tmp_path / "sources.toml"
    toml.write_text(f'[[snapshot]]\npath = "{SNAPSHOTS / "canvas.json"}"\n'
                    f'[[snapshot]]\npath = "{tmp_path / "missing.json"}"\n')
    results = run.collect({"live": str(toml)})
    assert [r.name for r in results] == ["canvas", "missing"]
    assert results[0].error is None and len(results[0].snapshot.items) == 2
    assert results[1].error and results[1].snapshot is None     # one bad entry fails alone
