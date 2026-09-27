"""Fusion core: SCENARIO.md's expected table exactly, plus adversarial cases."""
import itertools
import random
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from fusion import fuse as F
from fusion.model import CourseKey, CourseObservation, Observation, Snapshot
from tests import scenario as S


def _fused():
    return F.fuse(S.snapshots())


def _names(track):
    return {S.NAME_OF[(m.source, m.source_id)] for m in track.members}


# --------------------------------------------------------------------------- the scenario table

def test_scenario_exact_tracks():
    courses, tracks, warnings = _fused()
    assert warnings == []
    assert sum(len(s.items) for s in S.snapshots()) == 19
    assert len(tracks) == 14
    got = {frozenset(_names(t)): t for t in tracks}
    assert set(got) == {frozenset(e[2]) for e in S.EXPECTED}, "exactly these tracks, no others"
    for course, title, members, auth, conflicts, ev_kinds, action_url, st in S.EXPECTED:
        tr = got[frozenset(members)]
        ctx = f"{course} {title}"
        assert F.course_name(tr.course) == course, ctx
        assert tr.title.value == title, ctx
        if auth is None:
            assert tr.due is None, ctx
        else:
            a = S.OBS[auth]
            assert (tr.due.source, tr.due.source_id) == (a.source, a.source_id), ctx
            assert tr.due.value == a.due, ctx
            assert (tr.title.source, tr.title.source_id) == (a.source, a.source_id), ctx
        assert [(S.NAME_OF[(c.source, c.source_id)], round((c.value - c.chosen).total_seconds() / 60))
                for c in tr.conflicts] == conflicts, ctx
        assert {e["kind"] for e in tr.evidence} == ev_kinds, ctx
        assert tr.action_url == action_url, ctx
        assert F.status(tr, S.NOW) == st, ctx
        assert tr.links == {m.source: m.url for m in tr.members}, ctx
        assert tr.warnings == [], ctx


def test_scenario_evidence_details():
    _, tracks, _ = _fused()
    got = {frozenset(_names(t)): t for t in tracks}
    q1 = got[frozenset({"P1", "M5", "C1"})]
    pairs = {frozenset({S.NAME_OF[e["a"]], S.NAME_OF[e["b"]]}): e for e in q1.evidence}
    assert pairs[frozenset({"M5", "P1"})]["kind"] == "link"
    assert pairs[frozenset({"C1", "P1"})]["kind"] == "link"
    # the link direction: M5 -> P1 and C1 -> P1
    m5p1 = pairs[frozenset({"M5", "P1"})]["links"]
    assert m5p1 == [[["moodle", "cm:9"], ["prairielearn", "1:quiz1"]]]
    assert pairs[frozenset({"M5", "P1"})]["due_delta_min"] is None       # M5 undated
    assert pairs[frozenset({"C1", "P1"})]["due_delta_min"] == 0
    assert q1.due.source == "prairielearn" and q1.kind.value == "quiz"

    hw2 = got[frozenset({"W2", "M2"})]
    (e,) = hw2.evidence
    assert e["kind"] == "link" and e["due_delta_min"] == 59 and set(e["signals"]) == {"link", "title", "due"}
    (c,) = hw2.conflicts
    assert c.field == "due" and c.value == S.OBS["M2"].due and c.chosen == S.OBS["W2"].due

    ps3 = got[frozenset({"P2", "M7"})]
    (e,) = ps3.evidence
    assert e["kind"] == "title+due" and e["due_delta_min"] == 0 and e["links"] == []
    assert ps3.kind.value == "homework"


def test_scenario_courses():
    courses, _, _ = _fused()
    by = {F.course_name(c.key): c for c in courses}
    assert list(by) == ["CPSC 121 / 2026W1", "ENGL 110 / 2026W1", "MATH 100 / 2026W1"]
    cpsc = by["CPSC 121 / 2026W1"]
    assert {(d["source"], d["label"]) for d in cpsc.labels} == {
        ("moodle", "CPSC121-101-2026W1"), ("prairielearn", "CPSC 121"), ("canvas", "CPSC_121_101_2026W1")}
    assert cpsc.sections == ["101"]
    assert by["ENGL 110 / 2026W1"].sections == ["001"]
    assert {d["source"] for d in by["MATH 100 / 2026W1"].labels} == {"moodle", "webwork"}


def test_scenario_order_and_done():
    _, tracks, _ = _fused()
    ordered = F.order(tracks, S.NOW)
    names = [_names(t) for t in ordered]
    assert names[0] == {"W1", "M1"}                       # overdue first
    assert names[-1] == {"M9"}                            # undated last
    dues = [t.due.value for t in ordered if t.due and F.status(t, S.NOW) != "overdue"]
    assert dues == sorted(dues)
    # mark HW1 done at its authority -> hidden unless all
    snaps = S.snapshots()
    snaps = [replace(s, items=tuple(replace(o, done=True) if o == S.OBS["W1"] else o for o in s.items)) for s in snaps]
    _, tracks2, _ = F.fuse(snaps)
    assert len(F.order(tracks2, S.NOW)) == 13
    assert len(F.order(tracks2, S.NOW, include_done=True)) == 14
    # done said by a NON-authority member doesn't count
    snaps = [replace(s, items=tuple(replace(o, done=True) if o == S.OBS["M1"] else o for o in s.items)) for s in S.snapshots()]
    _, tracks3, _ = F.fuse(snaps)
    hw1 = next(t for t in tracks3 if "W1" in _names(t))
    assert F.status(hw1, S.NOW) == "overdue"


def test_status_boundaries():
    _, tracks, _ = _fused()
    hw2 = next(t for t in tracks if _names(t) == {"W2", "M2"})
    due = hw2.due.value
    assert F.status(hw2, due - timedelta(hours=48)) == "due_soon"
    assert F.status(hw2, due - timedelta(hours=48, minutes=1)) == "upcoming"
    assert F.status(hw2, due + timedelta(seconds=1)) == "overdue"
    lab = next(t for t in tracks if _names(t) == {"P4"})
    assert F.status(lab, lab.opens.value + timedelta(minutes=1)) == "upcoming"
    with pytest.raises(ValueError):
        F.status(hw2, due.replace(tzinfo=None))


# --------------------------------------------------------------------------- adversarial

def course(src, cid, label, title="", term=None):
    return CourseObservation(src, cid, label, title, term, f"http://{src}.test/c/{cid}")


def obs(src, sid, title, due=None, cid="c", url=None, **kw):
    return Observation(src, sid, cid, kw.pop("kind", "assignment"), title, due, kw.pop("opens", None),
                       url or f"http://{src}.test/i/{sid}", **kw)


def snap(src, courses, items):
    return Snapshot(src, f"http://{src}.test", S.FETCHED, tuple(courses), tuple(items))


def two(a_items, b_items, a_label="CPSC121-101-2026W1", b_label="cpsc121_2026w1"):
    return [snap("a", [course("a", "c", a_label)], a_items), snap("b", [course("b", "c", b_label)], b_items)]


D = S.t(2026, 10, 16)


def test_quiz2_vs_quiz3_never_merge():
    _, tracks, _ = F.fuse(two([obs("a", "1", "Quiz 2", D)], [obs("b", "1", "Quiz 3", D)]))
    assert len(tracks) == 2
    assert not F.title_match("Quiz 2", "Quiz 3")
    assert not F.title_match("Quiz 2", "Quiz 12")
    assert not F.title_match("HW2", "HW 2.1")


def test_same_title_different_courses():
    snaps = two([obs("a", "1", "Assignment 1", D)], [obs("b", "1", "Assignment 1", D)],
                a_label="MATH100-2026W1", b_label="ENGL110-001-2026W1")
    _, tracks, _ = F.fuse(snaps)
    assert len(tracks) == 2


def test_same_title_different_terms():
    snaps = two([obs("a", "1", "Assignment 1", D)], [obs("b", "1", "Assignment 1", D)],
                a_label="CPSC121-2026W1", b_label="CPSC121-2026W2")
    assert len(F.fuse(snaps)[1]) == 2


def test_same_source_never_merges():
    s = [snap("a", [course("a", "c", "CPSC121-2026W1")],
              [obs("a", "1", "Quiz 1", D), obs("a", "2", "Quiz 1", D, links_out=("http://a.test/i/1",))])]
    _, tracks, _ = F.fuse(s)
    assert len(tracks) == 2


def test_same_source_same_id_is_one_observation():
    o = obs("a", "1", "Quiz 1", D)
    s = [snap("a", [course("a", "c", "CPSC121-2026W1")], [o]), snap("a", [course("a", "c", "CPSC121-2026W1")], [o])]
    _, tracks, _ = F.fuse(s)
    assert len(tracks) == 1 and len(tracks[0].members) == 1


def test_transitive_chain_split_and_warn():
    # b1 links to a1; b1 also title+due matches a2 (same source as a1, different id).
    # Union-find would put a1 and a2 together: must split, keep the strong link edge, warn.
    a1 = obs("a", "1", "Lab 4", D, url="http://a.test/lab4-section-a")
    a2 = obs("a", "2", "Lab 4", D + timedelta(hours=1), url="http://a.test/lab4-section-b")
    b1 = obs("b", "1", "Lab 4", D, links_out=("http://a.test/lab4-section-a",))
    _, tracks, warnings = F.fuse(two([a1, a2], [b1]))
    groups = sorted(sorted(f"{m.source}{m.source_id}" for m in t.members) for t in tracks)
    assert groups == [["a1", "b1"], ["a2"]]
    assert len(warnings) == 1 and "same source" in warnings[0] and "a:2" in warnings[0]
    assert all(t.warnings == warnings for t in tracks)
    for t in tracks:
        assert len({m.source for m in t.members}) == len(t.members)


def test_three_source_chain_split():
    # c1 matches a1 by link and a2 by title (a2 undated); b1 matches a2 by link: chain a1-c1-a2-b1
    a1 = obs("a", "1", "Quiz 5", D)
    a2 = obs("a", "2", "Quiz 5", None, url="http://a.test/other")
    b1 = obs("b", "1", "Quiz five", None, links_out=("http://a.test/other",))
    c1 = obs("c", "1", "Quiz 5", D, links_out=("http://a.test/i/1",))
    snaps = two([a1, a2], [b1]) + [snap("c", [course("c", "c", "CPSC_121_101_2026W1")], [c1])]
    _, tracks, warnings = F.fuse(snaps)
    for t in tracks:
        assert len({m.source for m in t.members}) == len(t.members)
    groups = sorted(sorted(f"{m.source}{m.source_id}" for m in t.members) for t in tracks)
    assert ["a1", "c1"] in groups and any("a2" in g and "b1" in g for g in groups)
    assert warnings


@pytest.mark.parametrize("a,b", [
    ("http://x.test/webwork2/c/HW2/", "http://x.test/webwork2/c/HW2"),
    ("http://X.Test/webwork2/c/HW2", "http://x.test/webwork2/c/HW2"),
    ("https://x.test/webwork2/c/HW2", "http://x.test/webwork2/c/HW2"),
    ("http://x.test:80/a", "https://x.test:443/a"),
    ("http://x.test/a?user=fstudent&key=abc123", "http://x.test/a"),
    ("http://x.test/a?utm_source=moodle", "http://x.test/a"),
    ("http://x.test/view.php?id=3&action=editsubmission", "http://x.test/view.php?id=3"),
    ("http://x.test/view.php?b=2&id=3", "http://x.test/view.php?id=3&b=2"),
    ("http://127.0.0.1:3100/pl/course_instance/1/assessment/3/", "http://localhost:3100/pl/course_instance/1/assessment/3"),
])
def test_url_normalisation_equal(a, b):
    assert F.normalize_url(a) == F.normalize_url(b)


@pytest.mark.parametrize("a,b", [
    ("http://x.test/view.php?id=3", "http://x.test/view.php?id=4"),
    ("http://x.test:8081/a", "http://x.test:8082/a"),
    ("http://x.test/a/HW2", "http://x.test/a/HW20"),
    ("http://m.test/calendar/view.php?course=2&time=1#event_6", "http://m.test/calendar/view.php?course=2&time=1#event_7"),
])
def test_url_normalisation_distinct(a, b):
    assert F.normalize_url(a) != F.normalize_url(b)


def test_link_evidence_via_normalised_url():
    a = obs("a", "1", "Something", D, url="http://x.test/webwork2/c/HW2")
    b = obs("b", "1", "Unrelated title", D + timedelta(days=3), links_out=("HTTPS://X.TEST/webwork2/c/HW2/",))
    _, tracks, _ = F.fuse(two([a], [b]))
    (t,) = tracks
    assert t.evidence[0]["kind"] == "link" and t.due.source == "a"


def test_link_to_submit_url_counts():
    a = obs("a", "1", "X", D, submit_url="http://a.test/submit/1")
    b = obs("b", "1", "Y", None, links_out=("http://a.test/submit/1",))
    (t,) = F.fuse(two([a], [b]))[1]
    assert t.action_url == "http://a.test/submit/1"


@pytest.mark.parametrize("a,b", [
    ("HW2", "Homework 2"), ("WeBWorK HW1", "Homework 1"), ("hw02", "Homework 2 (WeBWorK)"),
    ("PS3", "Problem Set 3 due"), ("MP1", "Machine Problem 1"), ("PrairieLearn Quiz 1", "Quiz 1 (PrairieLearn)"),
    ("The Quiz 1 (online)", "quiz 1"),
])
def test_abbreviation_and_filler(a, b):
    assert F.title_match(a, b)


def test_abbreviation_merges_tracks():
    _, tracks, _ = F.fuse(two([obs("a", "1", "HW2", D)], [obs("b", "1", "Homework 2", D - timedelta(hours=3))]))
    (t,) = tracks
    assert t.evidence[0]["kind"] == "title+due" and t.evidence[0]["due_delta_min"] == 180


def test_title_needs_due_or_undated():
    far = D + timedelta(days=2)
    _, tracks, _ = F.fuse(two([obs("a", "1", "Quiz 1", D)], [obs("b", "1", "Quiz 1", far)]))
    assert len(tracks) == 2               # same title, dues 48 h apart: different things
    _, tracks, _ = F.fuse(two([obs("a", "1", "Quiz 1", D)], [obs("b", "1", "Quiz 1", D + timedelta(hours=24))]))
    assert len(tracks) == 1               # 24 h inclusive
    _, tracks, _ = F.fuse(two([obs("a", "1", "Reading 1")], [obs("b", "1", "Reading 1")]))
    assert len(tracks) == 1 and tracks[0].evidence[0]["kind"] == "title+undated"


def test_platform_only_title_never_matches():
    assert not F.title_match("WeBWorK", "Canvas")


@pytest.mark.parametrize("label,title,term,expect,section", [
    ("CPSC121-101-2026W1", "", None, CourseKey("CPSC", "121", "2026W1"), "101"),
    ("cpsc121_2026w1", "", None, CourseKey("CPSC", "121", "2026W1"), None),
    ("CPSC 121: Models of Computation, 2026 Winter Term 1", "", None, CourseKey("CPSC", "121", "2026W1"), None),
    ("CPSC_121_101_2026W1", "", None, CourseKey("CPSC", "121", "2026W1"), "101"),
    ("CPSC 121, 2026W1", "CPSC 121: Models of Computation, 2026 Winter Term 1", "2026 Winter Term 1",
     CourseKey("CPSC", "121", "2026W1"), None),
    ("CPSC 121", "Models of Computation", "2026 Winter Term 1", CourseKey("CPSC", "121", "2026W1"), None),
    ("MATH100-2026W1", "MATH 100 Differential Calculus", None, CourseKey("MATH", "100", "2026W1"), None),
    ("ENGL110-001-2026W1", "", None, CourseKey("ENGL", "110", "2026W1"), "001"),
    ("math100_2026w1", "math100 2026w1", None, CourseKey("MATH", "100", "2026W1"), None),
    ("MATH_100_L1A_2026S2", "", None, CourseKey("MATH", "100", "2026S2"), "L1A"),
])
def test_course_label_styles(label, title, term, expect, section):
    assert F.parse_course(label, title, term) == (expect, section)


@pytest.mark.parametrize("label,title,term", [
    ("Personal", "", None), ("Sandbox course", "Test", None), ("CPSC121", "Models of Computation", None),
])
def test_unparseable_course(label, title, term):
    assert F.parse_course(label, title, term) == (None, None)


def test_unparseable_course_kept_apart_and_warned():
    snaps = two([obs("a", "1", "Quiz 1", D)], [obs("b", "1", "Quiz 1", D)], a_label="CPSC121-2026W1", b_label="Weird Sandbox")
    courses, tracks, warnings = F.fuse(snaps)
    assert len(tracks) == 2
    assert any("Weird Sandbox" in w for w in warnings)
    unresolved = [c for c in courses if isinstance(c.key, str)]
    assert len(unresolved) == 1 and unresolved[0].warnings
    assert {F.course_name(t.course) for t in tracks} == {"CPSC 121 / 2026W1", "b:Weird Sandbox"}


def test_two_unparseable_courses_same_label_different_sources_stay_apart():
    snaps = two([obs("a", "1", "Quiz 1", D)], [obs("b", "1", "Quiz 1", D)], a_label="Sandbox", b_label="Sandbox")
    assert len(F.fuse(snaps)[1]) == 2


def test_naive_datetime_rejected():
    naive = D.replace(tzinfo=None)
    with pytest.raises(ValueError, match="naive"):
        F.fuse(two([obs("a", "1", "Quiz 1", naive)], []))
    with pytest.raises(ValueError, match="naive"):
        F.fuse(two([obs("a", "1", "Quiz 1", D, opens=naive)], []))


def test_deterministic_ids_across_permutations():
    base = S.snapshots()
    ref_courses, ref, ref_w = F.fuse(base)
    ref_ids = sorted(t.id for t in ref)
    ref_json = [F.track_json(t, S.NOW, full=True) for t in ref]
    rng = random.Random(1234)
    perms = list(itertools.permutations(base))
    for snaps in perms[:24]:
        shuffled = [replace(s, items=tuple(rng.sample(s.items, len(s.items))),
                            courses=tuple(rng.sample(s.courses, len(s.courses)))) for s in snaps]
        _, tracks, _ = F.fuse(shuffled)
        assert sorted(t.id for t in tracks) == ref_ids
        assert [F.track_json(t, S.NOW, full=True) for t in tracks] == ref_json


def test_track_id_is_hash_of_members():
    _, tracks, _ = _fused()
    q1 = next(t for t in tracks if _names(t) == {"P1", "M5", "C1"})
    assert q1.id == F.track_id(list(reversed(q1.members)))
    assert len({t.id for t in tracks}) == 14


def test_submit_authority_fallbacks():
    # no links: the only one with submit_url wins even if not earliest
    a = obs("a", "1", "Essay 1", D - timedelta(hours=2))
    b = obs("b", "1", "Essay 1", D, submit_url="http://b.test/submit")
    (t,) = F.fuse(two([a], [b]))[1]
    assert t.due.source == "b" and t.action_url == "http://b.test/submit"
    assert [c.source for c in t.conflicts] == ["a"]
    # no links, no submit_url: earliest due; a calendar event loses a tie
    ev = obs("a", "1", "Essay 1", D, kind="event")
    asg = obs("b", "1", "Essay 1", D)
    (t,) = F.fuse(two([ev], [asg]))[1]
    assert t.due.source == "b" and t.kind.value == "assignment"
    # within 5 min: no conflict
    x = obs("a", "1", "Essay 1", D, submit_url="http://a.test/s")
    y = obs("b", "1", "Essay 1", D + timedelta(minutes=5))
    (t,) = F.fuse(two([x], [y]))[1]
    assert t.conflicts == []


def test_authority_undated_falls_back_to_dated_member():
    a = obs("a", "1", "Quiz 7", None, url="http://a.test/q7")
    b = obs("b", "1", "Quiz 7", D, links_out=("http://a.test/q7",))
    (t,) = F.fuse(two([a], [b]))[1]
    assert t.action_url == "http://a.test/q7" and t.title.source == "a"
    assert t.due.source == "b" and t.due.value == D


def test_kind_most_specific():
    (t,) = F.fuse(two([obs("a", "1", "Midterm 1", D, kind="event")], [obs("b", "1", "Midterm 1", D, kind="exam")]))[1]
    assert t.kind.value == "exam" and t.kind.source == "b"


def test_item_with_unknown_course_is_kept_and_warned():
    s = [snap("a", [], [obs("a", "1", "Quiz 1", D, cid="ghost")])]
    _, tracks, warnings = F.fuse(s)
    assert len(tracks) == 1 and any("ghost" in w for w in warnings)


def test_json_helpers_roundtrip_types():
    import json
    _, tracks, _ = _fused()
    for t in tracks:
        json.dumps(F.track_json(t, S.NOW, full=True))
    hw2 = next(t for t in tracks if _names(t) == {"W2", "M2"})
    j = F.track_json(hw2, S.NOW, full=True)
    assert j["conflicts"][0]["delta_min"] == -59 and j["provenance"]["due"]["source"] == "webwork"


# --------------------------------------------------------------------------- real captured snapshots

SNAPDIR = Path(__file__).resolve().parent.parent / "fixtures" / "snapshots"


@pytest.mark.skipif(not (SNAPDIR / "moodle.json").exists(), reason="no captured snapshots")
def test_real_captured_snapshots_fuse():
    """Snapshots captured from the real Moodle/WeBWorK/PrairieLearn oracles (other agents' output).

    Real-server quirks this covers: PL reachable as 127.0.0.1 while Moodle links localhost,
    trailing-slash differences, PL "CPSC 121, 2026W1" labels.
    """
    from fusion.snapshot_io import load_dir
    snaps = load_dir(SNAPDIR)
    _, tracks, warnings = F.fuse(snaps)
    by_title = {(F.course_name(t.course), t.title.value): t for t in tracks}
    q1 = by_title.get(("CPSC 121 / 2026W1", "Quiz 1"))
    assert q1 and {m.source for m in q1.members} >= {"prairielearn", "moodle"}
    hw2 = by_title[("MATH 100 / 2026W1", "HW2")]
    assert {m.source for m in hw2.members} == {"webwork", "moodle"} and len(hw2.conflicts) == 1
    ps3 = by_title[("CPSC 121 / 2026W1", "Problem Set 3")]
    assert {m.source for m in ps3.members} == {"prairielearn", "moodle"}
    assert ("CPSC 121 / 2026W1", "Quiz 2") in by_title and ("CPSC 121 / 2026W1", "Quiz 3") in by_title
    assert not warnings


# --------------------------------------------------------------------------- review regressions

@pytest.mark.parametrize("bad", ["http://h:99999/x", "http://h:abc/x", "http://[bad/x"])
def test_normalize_url_is_total(bad):
    assert F.normalize_url(bad) is None


def test_bad_link_in_one_source_does_not_break_the_fuse():
    good = obs("a", "1", "Quiz 1", D, url="http://pl.test/q1")
    typo = obs("b", "1", "Something else", D, links_out=("http://localhost:99999/x", "http://[bad/x"))
    _, tracks, warnings = F.fuse(two([good], [typo]))
    assert sorted(t.title.value for t in tracks) == ["Quiz 1", "Something else"]
    bad = [w for w in warnings if "unparseable URL" in w]
    assert len(bad) == 2 and all("b:1" in w for w in bad)


def test_generic_list_link_is_not_link_evidence():
    # PL-style: an unopened assessment's url is its list page (with the row label as fragment,
    # as the adapter now emits it); a generic "do your PL work here" link must not merge.
    lab4 = obs("a", "L4", "Lab 4", D, url="http://pl.test/ci/1/assessments#L4")
    quiz3 = obs("b", "8", "Quiz 3", D, links_out=("http://pl.test/ci/1/assessments",))
    _, tracks, _ = F.fuse(two([lab4], [quiz3]))
    assert sorted(t.title.value for t in tracks) == ["Lab 4", "Quiz 3"]


def test_url_shared_by_two_same_source_items_is_not_a_deep_link():
    lab4 = obs("a", "L4", "Lab 4", D, url="http://pl.test/ci/1/assessments")
    lab5 = obs("a", "L5", "Lab 5", D, url="http://pl.test/ci/1/assessments")
    quiz3 = obs("b", "8", "Quiz 3", D, links_out=("http://pl.test/ci/1/assessments",))
    _, tracks, warnings = F.fuse(two([lab4, lab5], [quiz3]))
    assert sorted(t.title.value for t in tracks) == ["Lab 4", "Lab 5", "Quiz 3"]
    assert all(len(t.members) == 1 for t in tracks)
    assert not any("split a transitive merge" in w for w in warnings)
    assert any("not used as evidence" in w and "b:8" in w for w in warnings)


def test_link_to_course_page_is_not_link_evidence():
    a1 = obs("a", "1", "Lab 4", D)
    b1 = obs("b", "1", "Quiz 3", D, links_out=("http://a.test/c/c",))    # a's course page
    assert len(F.fuse(two([a1], [b1]))[1]) == 2


@pytest.mark.parametrize("x,y", [
    ("Week 2 Quiz 3", "Week 3 Quiz 2"), ("Lab 1 Part 2", "Lab 2 Part 1"), ("Lab 4.1", "Lab 1.4"),
    ("Lab 4.1", "Lab 4 1"), ("HW 2a", "HW 2"), ("Assignment 1a", "Assignment 1"), ("HW 2a", "HW 2b"),
])
def test_title_numbers_are_ordered_identifiers(x, y):
    assert not F.title_match(x, y)
    _, tracks, _ = F.fuse(two([obs("a", "1", x, D)], [obs("b", "1", y, D)]))
    assert len(tracks) == 2


@pytest.mark.parametrize("x,y", [
    ("HW 2a", "Homework 2A"), ("HW 2 a", "HW 2a"), ("Lab 04.1", "Lab 4.1"), ("Quiz 1 due at 10am", "Quiz 1 10am"),
    ("Read a chapter 4", "Read chapter 4"),
])
def test_title_identifier_equivalents(x, y):
    assert F.title_match(x, y)


def test_submit_authority_is_the_sink_of_a_link_chain():
    # canvas -> moodle pointer -> PL; the stale pointer is due 1 h earlier
    p = obs("p", "q1", "Quiz 1", D, url="http://p.test/q1")
    m = obs("m", "5", "PrairieLearn Quiz 1", D - timedelta(hours=1), url="http://m.test/5",
            links_out=("http://p.test/q1",))
    c = obs("c", "1", "Quiz 1 (PrairieLearn)", D, links_out=("http://m.test/5",))
    snaps = [snap(s, [course(s, "c", "CPSC121-2026W1")], [o]) for s, o in (("p", p), ("m", m), ("c", c))]
    (t,) = F.fuse(snaps)[1]
    assert t.action_url == "http://p.test/q1" and t.title.source == "p" and t.due.source == "p"
    assert [(k.source, round((k.value - k.chosen).total_seconds() / 60)) for k in t.conflicts] == [("m", -60)]


def test_due_arithmetic_uses_instants_across_dst_with_shared_zoneinfo():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    van = ZoneInfo("America/Vancouver")          # one cached object for both sides
    a_due = datetime(2026, 10, 31, 2, 0, tzinfo=van)                 # PDT
    b_due = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=van)         # PST: 24.5 real hours later
    assert (b_due - a_due) < timedelta(hours=24)            # Python's wall-clock arithmetic
    _, tracks, _ = F.fuse(two([obs("a", "1", "Quiz 1", a_due)], [obs("b", "1", "Quiz 1", b_due)]))
    assert len(tracks) == 2
    # 01:30 PDT vs 01:30 PST: an hour apart, a conflict
    pdt = datetime(2026, 11, 1, 1, 30, tzinfo=van)
    pst = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=van)
    auth = obs("a", "1", "Quiz 1", pdt, submit_url="http://a.test/s/1")
    other = obs("b", "1", "Quiz 1", pst)
    (t,) = F.fuse(two([auth], [other]))[1]
    assert [(c.source, c.source_id) for c in t.conflicts] == [("b", "1")]
    assert F.status(t, datetime(2026, 11, 1, 1, 0, fold=1, tzinfo=van)) == "overdue"  # 01:00 PST > 01:30 PDT


def test_duplicate_identity_with_different_content_warns_and_is_order_independent():
    a1 = obs("a", "3", "Assignment 1", D)
    a2 = obs("a", "3", "Essay draft", D + timedelta(days=3))
    c = [course("a", "c", "CPSC121-2026W1")]
    outs = []
    for items in ([a1], [a2]), ([a2], [a1]):
        _, tracks, warnings = F.fuse([snap("a", c, items[0]), snap("a", c, items[1])])
        assert any("appears 2 times" in w and "a:3" in w for w in warnings)
        outs.append([(t.id, t.title.value, t.due.value) for t in tracks])
    assert outs[0] == outs[1]


def test_percent_encoding_is_normalised():
    assert F.normalize_url("http://h/Quiz%201") == F.normalize_url("http://h/Quiz 1")
    assert F.normalize_url("http://h/p?q=a%20b") == F.normalize_url("http://h/p?q=a+b")
    assert F.normalize_url("http://h/a%2Db") == F.normalize_url("http://h/a-b")
