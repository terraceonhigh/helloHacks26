"""Oracle tests for PR #33 (canonical course codes in hub/db.py).

These pin down three joins a reviewer found broken on the PR head. They are
tests only, not a fix: each docstring says what hub.db should do, and where
"correct" is a judgment call it says which rule the test encodes, as a
proposal for Jacky to accept or change.
"""
from datetime import datetime, timezone

from hub import db
from hub.models import Course, Item

DUE = datetime(2026, 10, 2, 6, 59, tzinfo=timezone.utc)


def _course_rows(conn, code):
    return [row for row in db.courses(conn) if row[0] == code]


def test_same_course_with_different_term_strings_is_one_row():
    """One real course must be one `courses` row, whatever term string each
    source uses for it.

    Canvas sends `term.name` ("2026 Winter Term 1"), Workday "2026W1", and
    PrairieLearn "" when its title doesn't parse. `courses` is
    UNIQUE(code, term), so today each spelling gets its own row and the
    canonical code alone doesn't join them.

    Proposed rule for Jacky: normalise the term to the short UBC form
    ("2026W1"). An empty term means "unknown", so it attaches to the
    existing row with that code instead of making a new one, and a row saved
    with an unknown term takes the real term once a source supplies it.
    """
    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121", section="", term="", title="CPSC 121")])
    db.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026 Winter Term 1",
                          title="Models of Computation", grade=84.0)])
    db.save(conn, [Course(code="CPSC 121", section="101", term="2026W1", title="Models of Computation")])

    rows = _course_rows(conn, "CPSC 121")
    assert len(rows) == 1, f"CPSC 121 split across {len(rows)} rows by term string: {rows}"


def test_lab_shell_without_grade_does_not_erase_lecture_grade():
    """Saving a course with grade None must not overwrite a real grade.

    Canvas has separate lecture and lab shells ("CPSC 121 101 2026W1" and
    "CPSC 121 L1A 2026W1"). Both canonicalise to "CPSC 121", so they share
    one row, and whichever is saved last wins. Only the lecture shell
    carries a score, so the lab shell turns 84 into None.

    Proposed rule for Jacky: None means "this source doesn't know", never
    "no grade", so a known grade survives an unknown one
    (COALESCE(new, old)). When two shells both carry a real grade the last
    one still wins. That's a separate question and this test doesn't
    decide it.
    """
    conn = db.connect(":memory:")
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                     title="Models of Computation", grade=84.0)
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                 title="Models of Computation (Lab)", grade=None)
    db.save(conn, [lecture, lab])

    rows = _course_rows(conn, "CPSC 121")
    assert [r[3] for r in rows] == [84.0], f"lecture grade 84 lost to the lab shell: {rows}"


def test_lecture_and_lab_share_one_title_the_shorter_one_wins():
    """Jacky's answer to #41 ("lecture and lab should be one course"): the
    merge is right, but title needs the same explicit rule as grade instead
    of last-write-wins. Rule: shorter title wins, since a lab shell that
    differs at all tends to be the lecture's title with "(Lab)" tacked on.
    Order-independent, unlike raw last-write-wins."""
    conn = db.connect(":memory:")
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                     title="Models of Computation")
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                 title="Models of Computation (Lab)")

    db.save(conn, [lecture, lab])  # lecture first
    assert [r[2] for r in _course_rows(conn, "CPSC 121")] == ["Models of Computation"]

    conn2 = db.connect(":memory:")
    db.save(conn2, [lab, lecture])  # lab first - same result either way
    assert [r[2] for r in _course_rows(conn2, "CPSC 121")] == ["Models of Computation"]


def test_none_term_does_not_crash_canonicalization():
    # Canvas can send term.name: null; _canonical_term used to call .strip() on it.
    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121", section="", term=None, title="CPSC 121")])
    assert [r[0] for r in _course_rows(conn, "CPSC 121")] == ["CPSC 121"]


def test_orphaned_item_links_to_course_once_it_arrives():
    """An item saved before its course (course_id NULL) must be linked when
    it's saved again and the course is now known.

    Today the item upsert's DO UPDATE clause leaves course_id alone, so an
    item that was orphaned once shows "(unknown course)" forever, even after
    re-fetches that include its course.

    Proposed rule for Jacky: every upsert takes the newly resolved course_id
    when it has one, and keeps the old one when it doesn't (so a later call
    without the course can't unlink it: COALESCE(new, old)). The stronger
    rule, "linked as soon as the course arrives, even with no re-save of
    the item", would need `items` to store the raw course code, which is a
    schema change for Jacky to decide on. This test doesn't require it.
    """
    conn = db.connect(":memory:")
    quiz = Item(course="CPSC 121 101 2026W1", category="deadline", kind="quiz", title="Quiz 3",
                due=DUE, url="https://canvas.example/quiz/3", source="canvas")
    db.save(conn, [], [quiz])  # course not known yet -> orphan
    db.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                          title="Models of Computation")], [quiz])  # re-fetch, course now present

    codes = [row[0] for row in db.upcoming(conn)]
    assert codes == ["CPSC 121"], f"orphaned item never re-linked to its course: {codes}"
