"""Network-free: replay what the real Moodle 4.5 server returned (fixtures/moodle/,
captured by `python -m oracles.moodle_oracle --save-fixtures`) through the adapter."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup

from fusion import snapshot_io
from fusion.adapters import moodle
from oracles.moodle.replay import ReplaySession

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures" / "moodle"
BASE = "http://localhost:8082"
VAN = ZoneInfo("America/Vancouver")
WW = "http://localhost:8081/webwork2/math100_2026w1"


def at(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=VAN)


@pytest.fixture(scope="module")
def snap():
    return moodle.fetch(ReplaySession(FIX), BASE)


def item(snap, label, title):
    course = {c.label: c.source_id for c in snap.courses}[label]
    found = [o for o in snap.items if o.course_source_id == course and o.title == title]
    assert len(found) == 1, (label, title, found)
    return found[0]


def test_courses(snap):
    assert {(c.label, c.title) for c in snap.courses} == {
        ("MATH100-2026W1", "MATH 100 Differential Calculus"),
        ("CPSC121-101-2026W1", "CPSC 121 101 Models of Computation"),
        ("ENGL110-001-2026W1", "ENGL 110 Approaches to Literature"),
    }
    assert all(c.source == "moodle" and "/course/view.php?id=" in c.url for c in snap.courses)


# (course, title, kind, due, links_out, has submit_url)
SCENARIO = [
    ("MATH100-2026W1", "WeBWorK HW1", "assignment", "2026-09-20 23:59", (f"{WW}/HW1/",), False),
    ("MATH100-2026W1", "Homework 2 (WeBWorK)", "assignment", "2026-09-29 23:00", (f"{WW}/HW2/",), False),
    ("MATH100-2026W1", "Midterm 1", "exam", "2026-10-15 18:00", (), False),
    ("MATH100-2026W1", "Assignment 1", "assignment", "2026-10-09 23:59", (), True),
    ("CPSC121-101-2026W1", "PrairieLearn Quiz 1", "assignment", None, None, False),
    ("ENGL110-001-2026W1", "Assignment 1", "assignment", "2026-10-09 23:59", (), True),
    ("CPSC121-101-2026W1", "Problem Set 3 due", "event", "2026-10-05 17:00", (), False),
    ("CPSC121-101-2026W1", "Quiz 3", "assignment", "2026-10-16 23:59", (), True),
    ("ENGL110-001-2026W1", "Reading: Chapter 4", "reading", None, (), False),
]


@pytest.mark.parametrize("label,title,kind,due,links,submits", SCENARIO)
def test_scenario_items(snap, label, title, kind, due, links, submits):
    o = item(snap, label, title)
    assert o.kind == kind
    assert o.due == (at(due) if due else None)
    if o.due:
        assert o.due.tzinfo is not None and o.due.utcoffset() == o.due.astimezone(VAN).utcoffset()
    assert o.opens is None
    if links is not None:
        assert o.links_out == links
    assert (o.submit_url is not None) == submits
    assert "/course/view.php" not in o.url


def test_pl_link_captured(snap):
    o = item(snap, "CPSC121-101-2026W1", "PrairieLearn Quiz 1")
    assert len(o.links_out) == 1 and "/pl/course_instance/" in o.links_out[0] and "/assessment/" in o.links_out[0]
    assert o.due is None


def test_exactly_the_scenario(snap):
    assert len(snap.items) == 9   # the server made no extra items for these courses
    assert len({(o.source, o.source_id) for o in snap.items}) == 9


def test_urls_are_deep_links(snap):
    for o in snap.items:
        if o.source_id.startswith("cm:"):
            assert o.url.endswith(f"view.php?id={o.source_id[3:]}")
        else:
            assert o.url.endswith(f"#event_{o.source_id.split(':')[1]}")


def test_done_state(snap):
    assert item(snap, "MATH100-2026W1", "Assignment 1").done is False      # Moodle submission, not submitted
    assert item(snap, "MATH100-2026W1", "WeBWorK HW1").done is None        # pointer: Moodle can't tell


def test_saved_snapshot_roundtrips(snap):
    saved = snapshot_io.load(ROOT / "fixtures" / "snapshots" / "moodle.json")
    assert saved.items == snap.items and saved.courses == snap.courses


def test_extract_links_skips_same_host():
    frag = BeautifulSoup('<p><a href="http://localhost:8082/mod/assign/view.php?id=3">a</a> '
                         'see https://example.invalid/x. and <a href="http://localhost:8081/w/HW1/">w</a></p>', "html.parser")
    assert moodle.extract_links(frag, BASE) == ("http://localhost:8081/w/HW1/", "https://example.invalid/x")


def test_calendar_action_does_not_imply_submit():
    # The real server's calendar offers "Add submission" on WeBWorK HW1 (no submission
    # plugin); the adapter must trust the assignment page instead.
    o = moodle.fetch(ReplaySession(FIX), BASE)
    hw1 = item(o, "MATH100-2026W1", "WeBWorK HW1")
    assert hw1.submit_url is None


def test_logged_out_session_raises():
    class LoggedOut:
        def get(self, url, **kw):
            from oracles.moodle.replay import FakeResponse
            return FakeResponse(200, "<html>login</html>", url)
    with pytest.raises(moodle.MoodleError):
        moodle.fetch(LoggedOut(), BASE)


def test_extract_links_survives_bad_ports_and_hosts():
    html = ('<p><a href="http://pl.example.com:99999/q1">a</a> <a href="http://[bad/x">b</a> '
            '<a href="http://localhost:8082/mod/page/view.php?id=1">own</a> '
            '<a href="http://localhost:8081/webwork2/c/HW2/">ww</a></p>')
    got = moodle.extract_links(BeautifulSoup(html, "html.parser"), "http://localhost:8082")
    assert got == ("http://pl.example.com:99999/q1", "http://localhost:8081/webwork2/c/HW2/")
