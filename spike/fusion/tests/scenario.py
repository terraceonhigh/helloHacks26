"""SCENARIO.md's 19 observations, built synthetically as Snapshots (no network, no fixtures).

Labels, titles and URL shapes follow SCENARIO.md's course table and what the real
servers print (WeBWorK set URLs without a trailing slash, Moodle bodies linking
them with one; Moodle submit pages as ?id=N&action=editsubmission).

    snapshots() -> [Snapshot x4]     one per source
    OBS["W2"] -> Observation         by SCENARIO id
    EXPECTED                         the "Expected fused tracks" table
    NOW                              2026-09-27 12:00 PDT
"""
from datetime import datetime, timedelta, timezone

from fusion.model import CourseObservation, Observation, Snapshot

PDT = timezone(timedelta(hours=-7), "PDT")
PST = timezone(timedelta(hours=-8), "PST")
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=PDT)
FETCHED = datetime(2026, 9, 27, 11, 55, tzinfo=PDT)


def t(y, mo, d, h=23, mi=59, tz=PDT):
    return datetime(y, mo, d, h, mi, tzinfo=tz)


WW = "http://localhost:8081/webwork2/math100_2026w1"
PL = "http://localhost:3100/pl/course_instance/1"
MD = "http://localhost:8082"
CV = "http://canvas.example.invalid"


def ww(s):
    return f"{WW}/{s}"


def pl(n):
    return f"{PL}/assessment/{n}"


def md(cm):
    return f"{MD}/mod/assign/view.php?id={cm}"


COURSES = {
    "webwork": [CourseObservation("webwork", "math100_2026w1", "math100_2026w1", "math100 2026w1", None, WW)],
    "prairielearn": [CourseObservation("prairielearn", "1", "CPSC 121", "Models of Computation",
                                       "2026 Winter Term 1", PL)],
    "moodle": [
        CourseObservation("moodle", "2", "MATH100-2026W1", "MATH 100 Differential Calculus", None, f"{MD}/course/view.php?id=2"),
        CourseObservation("moodle", "3", "CPSC121-101-2026W1", "CPSC 121 101 Models of Computation", None, f"{MD}/course/view.php?id=3"),
        CourseObservation("moodle", "4", "ENGL110-001-2026W1", "ENGL 110 Approaches to Literature", None, f"{MD}/course/view.php?id=4"),
    ],
    "canvas": [CourseObservation("canvas", "101", "CPSC_121_101_2026W1", "CPSC 121 101 Models of Computation",
                                 "2026 Winter Term 1", f"{CV}/courses/101")],
}

OBS = {
    # WeBWorK (course math100_2026w1)
    "W1": Observation("webwork", "math100_2026w1/HW1", "math100_2026w1", "homework", "HW1",
                      t(2026, 9, 20), t(2026, 9, 1, 0, 0), ww("HW1"), done=False),
    "W2": Observation("webwork", "math100_2026w1/HW2", "math100_2026w1", "homework", "HW2",
                      t(2026, 9, 29), t(2026, 9, 15, 0, 0), ww("HW2"), done=False),
    "W3": Observation("webwork", "math100_2026w1/HW9", "math100_2026w1", "homework", "HW9",
                      t(2027, 1, 15, tz=PST), t(2026, 12, 1, 0, 0, tz=PST), ww("HW9")),
    "W4": Observation("webwork", "math100_2026w1/HW3", "math100_2026w1", "homework", "HW3",
                      t(2026, 10, 17), t(2026, 10, 10, 0, 0), ww("HW3")),
    # PrairieLearn (course CPSC 121, instance 2026W1)
    "P1": Observation("prairielearn", "1:quiz1", "1", "quiz", "Quiz 1", t(2026, 10, 2), t(2026, 9, 1, 0, 0), pl(1)),
    "P2": Observation("prairielearn", "1:ps3", "1", "homework", "Problem Set 3", t(2026, 10, 5, 17, 0), t(2026, 9, 1, 0, 0), pl(2)),
    "P3": Observation("prairielearn", "1:quiz2", "1", "quiz", "Quiz 2", t(2026, 10, 16), t(2026, 9, 1, 0, 0), pl(3)),
    "P4": Observation("prairielearn", "1:lab4", "1", "lab", "Lab 4", t(2026, 10, 27), t(2026, 10, 20, 0, 0), pl(4)),
    # Moodle
    "M1": Observation("moodle", "cm:1", "2", "assignment", "WeBWorK HW1", t(2026, 9, 20), None, md(1),
                      links_out=(ww("HW1") + "/",), excerpt="Do WeBWorK HW1 here: " + ww("HW1") + "/"),
    "M2": Observation("moodle", "cm:2", "2", "assignment", "Homework 2 (WeBWorK)", t(2026, 9, 29, 23, 0), None, md(2),
                      links_out=(ww("HW2") + "/",)),
    "M3": Observation("moodle", "event:6", "2", "event", "Midterm 1", t(2026, 10, 15, 18, 0), None,
                      f"{MD}/calendar/view.php?view=day&course=2#event_6"),
    "M4": Observation("moodle", "cm:3", "2", "assignment", "Assignment 1", t(2026, 10, 9), None, md(3),
                      submit_url=md(3) + "&action=editsubmission", done=False),
    "M5": Observation("moodle", "cm:9", "3", "assignment", "PrairieLearn Quiz 1", None, None, md(9),
                      links_out=(pl(1),)),
    "M6": Observation("moodle", "cm:5", "4", "assignment", "Assignment 1", t(2026, 10, 9), None, md(5),
                      submit_url=md(5) + "&action=editsubmission", done=False),
    "M7": Observation("moodle", "event:7", "3", "event", "Problem Set 3 due", t(2026, 10, 5, 17, 0), None,
                      f"{MD}/calendar/view.php?view=day&course=3#event_7"),
    "M8": Observation("moodle", "cm:6", "3", "assignment", "Quiz 3", t(2026, 10, 16), None, md(6),
                      submit_url=md(6) + "&action=editsubmission", done=False),
    "M9": Observation("moodle", "cm:7", "4", "reading", "Reading: Chapter 4", None, None,
                      f"{MD}/mod/page/view.php?id=7"),
    # Canvas
    "C1": Observation("canvas", "assignment:51001", "101", "assignment", "Quiz 1 (PrairieLearn)", t(2026, 10, 2), None,
                      f"{CV}/courses/101/assignments/51001", links_out=(pl(1),)),
    "C2": Observation("canvas", "assignment:51002", "101", "assignment", "Tutorial 2 worksheet", t(2026, 10, 1, 12, 0), None,
                      f"{CV}/courses/101/assignments/51002"),
}

NAME_OF = {(o.source, o.source_id): k for k, o in OBS.items()}


def snapshots() -> list[Snapshot]:
    out = []
    for src, base in (("webwork", "http://localhost:8081"), ("prairielearn", "http://localhost:3100"),
                      ("moodle", MD), ("canvas", CV)):
        items = tuple(o for o in OBS.values() if o.source == src)
        out.append(Snapshot(src, base, FETCHED, tuple(COURSES[src]), items))
    return out


# "Expected fused tracks": course, title, members, due authority, conflicts (id, minutes),
# merge evidence kinds, action_url, status at NOW
EXPECTED = [
    ("MATH 100 / 2026W1", "HW1", {"W1", "M1"}, "W1", [], {"link"}, ww("HW1"), "overdue"),
    ("MATH 100 / 2026W1", "HW2", {"W2", "M2"}, "W2", [("M2", -59)], {"link"}, ww("HW2"), "upcoming"),
    ("MATH 100 / 2026W1", "HW9", {"W3"}, "W3", [], set(), ww("HW9"), "not_open"),
    ("MATH 100 / 2026W1", "HW3", {"W4"}, "W4", [], set(), ww("HW3"), "not_open"),
    ("MATH 100 / 2026W1", "Midterm 1", {"M3"}, "M3", [], set(), OBS["M3"].url, "upcoming"),
    ("MATH 100 / 2026W1", "Assignment 1", {"M4"}, "M4", [], set(), OBS["M4"].submit_url, "upcoming"),
    ("CPSC 121 / 2026W1", "Quiz 1", {"P1", "M5", "C1"}, "P1", [], {"link", "title+undated"}, pl(1), "upcoming"),
    ("CPSC 121 / 2026W1", "Problem Set 3", {"P2", "M7"}, "P2", [], {"title+due"}, pl(2), "upcoming"),
    ("CPSC 121 / 2026W1", "Quiz 2", {"P3"}, "P3", [], set(), pl(3), "upcoming"),
    ("CPSC 121 / 2026W1", "Quiz 3", {"M8"}, "M8", [], set(), OBS["M8"].submit_url, "upcoming"),
    ("CPSC 121 / 2026W1", "Lab 4", {"P4"}, "P4", [], set(), pl(4), "not_open"),
    ("CPSC 121 / 2026W1", "Tutorial 2 worksheet", {"C2"}, "C2", [], set(), OBS["C2"].url, "upcoming"),
    ("ENGL 110 / 2026W1", "Assignment 1", {"M6"}, "M6", [], set(), OBS["M6"].submit_url, "upcoming"),
    ("ENGL 110 / 2026W1", "Reading: Chapter 4", {"M9"}, None, [], set(), OBS["M9"].url, "undated"),
]
