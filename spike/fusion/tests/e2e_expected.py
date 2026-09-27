"""SCENARIO.md's expected fused output, written out literally, plus a checker.

Shared by tests/test_e2e.py (over fixtures/snapshots/*.json, network-free) and
oracles/e2e_live.py (over a live fetch). Not collected by pytest (no test_ prefix).

The expected values come from SCENARIO.md (wall-clock times in America/Vancouver,
with the offset each server itself printed). They are NOT computed by
fusion/fuse.py, so a checker built on them can't agree with a fusion bug.

    check(snaps, now=NOW, live=False) -> list[str]     every mismatch, [] when exact
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fusion import fuse as F

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "fixtures" / "snapshots"

PDT = timezone(timedelta(hours=-7))
PST = timezone(timedelta(hours=-8))
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=PDT)

WW = "http://localhost:8081/webwork2/math100_2026w1"
PL = "http://127.0.0.1:3100/pl/course_instance/1"
MD = "http://localhost:8082"
CV = "http://canvas.example.invalid"

# SCENARIO id -> (source, resolved course, title as that server prints it).
# Identifying members by content, not by source_id, because Moodle cmids and PL
# assessment ids are assigned by the servers at seed time.
SCENARIO_OBS = {
    "W1": ("webwork", "MATH 100 / 2026W1", "HW1"),
    "W2": ("webwork", "MATH 100 / 2026W1", "HW2"),
    "W3": ("webwork", "MATH 100 / 2026W1", "HW9"),
    "W4": ("webwork", "MATH 100 / 2026W1", "HW3"),
    "P1": ("prairielearn", "CPSC 121 / 2026W1", "Quiz 1"),
    "P2": ("prairielearn", "CPSC 121 / 2026W1", "Problem Set 3"),
    "P3": ("prairielearn", "CPSC 121 / 2026W1", "Quiz 2"),
    "P4": ("prairielearn", "CPSC 121 / 2026W1", "Lab 4"),
    "M1": ("moodle", "MATH 100 / 2026W1", "WeBWorK HW1"),
    "M2": ("moodle", "MATH 100 / 2026W1", "Homework 2 (WeBWorK)"),
    "M3": ("moodle", "MATH 100 / 2026W1", "Midterm 1"),
    "M4": ("moodle", "MATH 100 / 2026W1", "Assignment 1"),
    "M5": ("moodle", "CPSC 121 / 2026W1", "PrairieLearn Quiz 1"),
    "M6": ("moodle", "ENGL 110 / 2026W1", "Assignment 1"),
    "M7": ("moodle", "CPSC 121 / 2026W1", "Problem Set 3 due"),
    "M8": ("moodle", "CPSC 121 / 2026W1", "Quiz 3"),
    "M9": ("moodle", "ENGL 110 / 2026W1", "Reading: Chapter 4"),
    "C1": ("canvas", "CPSC 121 / 2026W1", "Quiz 1 (PrairieLearn)"),
    "C2": ("canvas", "CPSC 121 / 2026W1", "Tutorial 2 worksheet"),
}

# Observations the platforms create on their own (e.g. a Moodle "course start"
# event). SCENARIO says: filter deliberately with a reason, or count them. The
# real captures currently contain NONE: the Moodle adapter only emits course
# modules and course-level calendar events, and the seed creates no others. If a
# capture grows one, it must be added here with its reason, or this test fails.
PLATFORM_EXTRAS: dict[tuple[str, str], str] = {}

# The instant each item is due, per SCENARIO (wall clock, with the server's offset).
DUE = {
    "W1": datetime(2026, 9, 20, 23, 59, tzinfo=PDT),
    "W2": datetime(2026, 9, 29, 23, 59, tzinfo=PDT),
    # after the BC time change: WeBWorK printed PST (-08:00); trust the server's zone
    "W3": datetime(2027, 1, 15, 23, 59, tzinfo=PST),
    "W4": datetime(2026, 10, 17, 23, 59, tzinfo=PDT),
    "P1": datetime(2026, 10, 2, 23, 59, tzinfo=PDT),
    "P2": datetime(2026, 10, 5, 17, 0, tzinfo=PDT),
    "P3": datetime(2026, 10, 16, 23, 59, tzinfo=PDT),
    "P4": datetime(2026, 10, 27, 23, 59, tzinfo=PDT),
    "M1": datetime(2026, 9, 20, 23, 59, tzinfo=PDT),
    "M2": datetime(2026, 9, 29, 23, 0, tzinfo=PDT),
    "M3": datetime(2026, 10, 15, 18, 0, tzinfo=PDT),
    "M4": datetime(2026, 10, 9, 23, 59, tzinfo=PDT),
    "M5": None,
    "M6": datetime(2026, 10, 9, 23, 59, tzinfo=PDT),
    "M7": datetime(2026, 10, 5, 17, 0, tzinfo=PDT),
    "M8": datetime(2026, 10, 16, 23, 59, tzinfo=PDT),
    "M9": None,
    # Canvas stores "11:59pm" as 23:59:59 local
    "C1": datetime(2026, 10, 2, 23, 59, 59, tzinfo=PDT),
    "C2": datetime(2026, 10, 1, 12, 0, tzinfo=PDT),
}


def _moodle_submit(obs):
    return obs.submit_url


# The "Expected fused tracks" table, row for row:
#   course, title, members, due authority, conflicts [(id, minutes)],
#   evidence edges {(a, b): kind}, link directions {(from, to)}, action_url, status at NOW.
# action_url is a literal (or a regex via re.compile, live only) where the page is fixed, or a function of the authority
# observation where the server assigned the id (Moodle cmids, Canvas ids).
EXPECTED = [
    ("MATH 100 / 2026W1", "HW1", {"W1", "M1"}, "W1", [], {("M1", "W1"): "link"}, {("M1", "W1")},
     f"{WW}/HW1", "overdue"),
    ("MATH 100 / 2026W1", "HW2", {"W2", "M2"}, "W2", [("M2", -59)], {("M2", "W2"): "link"}, {("M2", "W2")},
     f"{WW}/HW2", "upcoming"),
    ("MATH 100 / 2026W1", "HW9", {"W3"}, "W3", [], {}, set(), f"{WW}/HW9", "not_open"),
    ("MATH 100 / 2026W1", "HW3", {"W4"}, "W4", [], {}, set(), f"{WW}/HW3", "not_open"),
    ("MATH 100 / 2026W1", "Midterm 1", {"M3"}, "M3", [], {}, set(), lambda o: o.url, "upcoming"),
    ("MATH 100 / 2026W1", "Assignment 1", {"M4"}, "M4", [], {}, set(), _moodle_submit, "upcoming"),
    # SCENARIO evidence: link (M5->P1, C1->P1). M5 and C1 also match each other on
    # title with M5 undated; that edge is real, counted, and asserted, not ignored.
    ("CPSC 121 / 2026W1", "Quiz 1", {"P1", "M5", "C1"}, "P1", [],
     {("M5", "P1"): "link", ("C1", "P1"): "link", ("C1", "M5"): "title+undated"},
     {("M5", "P1"), ("C1", "P1")}, f"{PL}/assessment/3/", "upcoming"),
    # PS3: the PL oracle's click check starts the Homework, after which PrairieLearn
    # itself links the row to fstudent's instance, not /assessment/2/. The captured
    # state is the started one.
    ("CPSC 121 / 2026W1", "Problem Set 3", {"P2", "M7"}, "P2", [], {("M7", "P2"): "title+due"}, set(),
     f"{PL}/assessment_instance/1/", "upcoming"),
    ("CPSC 121 / 2026W1", "Quiz 2", {"P3"}, "P3", [], {}, set(), f"{PL}/assessment/4/", "upcoming"),
    ("CPSC 121 / 2026W1", "Quiz 3", {"M8"}, "M8", [], {}, set(), _moodle_submit, "upcoming"),
    # Lab 4: KNOWN DEVIATION from "PL lab4". Before it opens PrairieLearn lists it with
    # no link and never shows the student its assessment id (the real deep link 403s
    # until 2026-10-20). The adapter's url is the course instance's assessments page,
    # and it says so in the snapshot notes (asserted below), with the row label as a fragment so
    # the url is still this item's own and never matches a generic link to the list page.
    ("CPSC 121 / 2026W1", "Lab 4", {"P4"}, "P4", [], {}, set(), f"{PL}/assessments#L4", "not_open"),
    ("CPSC 121 / 2026W1", "Tutorial 2 worksheet", {"C2"}, "C2", [], {}, set(),
     f"{CV}/courses/4201/assignments/51002", "upcoming"),
    ("ENGL 110 / 2026W1", "Assignment 1", {"M6"}, "M6", [], {}, set(), _moodle_submit, "upcoming"),
    ("ENGL 110 / 2026W1", "Reading: Chapter 4", {"M9"}, None, [], {}, set(), lambda o: o.url, "undated"),
]




def match_ids(snaps, mapping):
    """SCENARIO id -> the one real observation with that (source, course, title), plus errors."""
    by_content: dict[tuple, list] = {}
    for s in snaps:
        for o in s.items:
            course = F.course_name(mapping.get((o.source, o.course_source_id), "?"))
            by_content.setdefault((o.source, course, o.title), []).append(o)
    obs, errors = {}, []
    for name, key in SCENARIO_OBS.items():
        found = by_content.get(key, [])
        if len(found) != 1:
            errors.append(f"{name} {key}: {len(found)} observations, want 1")
        else:
            obs[name] = found[0]
    return obs, errors


# Live only: PS3's url is /assessment/2/ on a fresh PrairieLearn seed and
# /assessment_instance/<n>/ once anything (the PL oracle's click check, or the
# student) has started the Homework. Both are PrairieLearn's own deep link for it.
PS3_LIVE = re.compile(re.escape(PL) + r"/(assessment/2|assessment_instance/\d+)/")


def check_row(row, tracks, obs, now=None, live=False) -> list[str]:
    course, title, members, auth, conflicts, edges, directions, action, want_status = row
    now = now or NOW
    errs = []
    tag = f"[{course} {title}]"
    if not all(m in obs for m in members):
        return [f"{tag} members not all found"]
    sid = {k: (o.source, o.source_id) for k, o in obs.items()}
    name_of = {v: k for k, v in sid.items()}
    want_members = {sid[m] for m in members}
    matches = [t for t in tracks if {(m.source, m.source_id) for m in t.members} == want_members]
    if len(matches) != 1:
        return [f"{tag} {len(matches)} tracks with exactly members {sorted(members)}"]
    t = matches[0]

    def eq(what, got, want):
        if got != want:
            errs.append(f"{tag} {what}: got {got!r}, want {want!r}")

    eq("course", F.course_name(t.course), course)
    eq("title", t.title.value, title)
    eq("id", t.id, F.track_id(t.members))
    if auth is None:
        eq("due", t.due, None)
    else:
        eq("due authority", t.due and (t.due.source, t.due.source_id), sid[auth])
        eq("due", t.due and t.due.value, DUE[auth])
        eq("title authority", (t.title.source, t.title.source_id), sid[auth])
    eq("conflicts", sorted((name_of.get((c.source, c.source_id)), c.field,
                            round((c.value - c.chosen).total_seconds() / 60)) for c in t.conflicts),
       sorted((n, "due", m) for n, m in conflicts))
    eq("evidence", {tuple(sorted((name_of.get(tuple(e["a"])), name_of.get(tuple(e["b"]))))): e["kind"]
                    for e in t.evidence},
       {tuple(sorted(k)): v for k, v in edges.items()})
    eq("link directions", {(name_of.get(tuple(a)), name_of.get(tuple(b))) for e in t.evidence for a, b in e["links"]},
       directions)
    if title == "Problem Set 3":
        eq("PS3 due delta / links", [(e["due_delta_min"], e["links"]) for e in t.evidence], [(0, [])])
        if live:
            if not PS3_LIVE.fullmatch(t.action_url):
                errs.append(f"{tag} action_url {t.action_url!r} is not PL's ps3 deep link")
            action = None
    if action is not None:
        eq("action_url", t.action_url, action(obs[auth or next(iter(members))]) if callable(action) else action)
    eq("status", F.status(t, now), want_status)
    return errs


def check(snaps, now=None, live=False) -> list[str]:
    """Every way the fused snaps differ from SCENARIO's expected table ([] = exact)."""
    courses, tracks, warnings = F.fuse(snaps)
    mapping, _, _ = F.resolve_courses(snaps)
    obs, errs = match_ids(snaps, mapping)
    known = {(o.source, o.source_id) for o in obs.values()}
    all_obs = [(o.source, o.source_id) for s in snaps for o in s.items]
    extras = sorted(o for o in all_obs if o not in known)
    if extras != sorted(PLATFORM_EXTRAS):
        errs.append(f"unlisted platform observations: {extras}")
    if len(all_obs) != 19 + len(PLATFORM_EXTRAS):
        errs.append(f"{len(all_obs)} observations, want {19 + len(PLATFORM_EXTRAS)}")
    for name, want in DUE.items():
        if name in obs and obs[name].due != want:
            errs.append(f"{name} due {obs[name].due} != SCENARIO {want}")
    if len(tracks) != len(EXPECTED):
        errs.append(f"{len(tracks)} tracks, want {len(EXPECTED)}")
    if warnings:
        errs.append(f"fusion warnings: {warnings}")
    for row in EXPECTED:
        errs.extend(check_row(row, tracks, obs, now, live))
    return errs
