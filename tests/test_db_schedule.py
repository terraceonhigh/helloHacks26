from datetime import date, time

from hub import db
from hub.models import Course, Meeting

COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")
LECTURE = Meeting(course="CPSC 121", kind="lecture", days=["MO", "WE", "FR"],
                   start_time=time(10, 0), end_time=time(11, 0), location="ICCS 101",
                   term_start=date(2026, 9, 8), term_end=date(2026, 12, 5), source="workday")


def test_save_and_schedule():
    conn = db.connect(":memory:")
    db.save(conn, [COURSE], meetings=[LECTURE])
    rows = db.schedule(conn)
    assert rows == [("CPSC 121", "lecture", "MO,WE,FR", "10:00:00", "11:00:00",
                      "ICCS 101", "2026-09-08", "2026-12-05", "workday")]


def test_save_is_idempotent_and_updates():
    conn = db.connect(":memory:")
    db.save(conn, [COURSE], meetings=[LECTURE])
    moved = Meeting(**{**LECTURE.__dict__, "location": "ICCS 200"})
    db.save(conn, [COURSE], meetings=[moved])
    rows = db.schedule(conn)
    assert len(rows) == 1
    assert rows[0][5] == "ICCS 200"


def test_a_second_distinct_time_slot_for_the_same_course_and_kind_is_kept_separately():
    # A lecture with two weekly slots at different times (e.g. Mon/Wed one
    # time, Fri another) must not collapse into one row.
    other_slot = Meeting(**{**LECTURE.__dict__, "days": ["FR"], "start_time": time(9, 0), "end_time": time(10, 0)})
    conn = db.connect(":memory:")
    db.save(conn, [COURSE], meetings=[LECTURE, other_slot])
    assert len(db.schedule(conn)) == 2


def test_meeting_with_unmatched_course_is_skipped_not_orphaned():
    conn = db.connect(":memory:")
    db.save(conn, [], meetings=[LECTURE])  # no course given this call
    assert db.schedule(conn) == []


def test_canvas_and_workday_join_the_same_course_row():
    # Same canonicalisation as items/textbooks (_canonical_code) - a meeting
    # saved under Workday's short code still joins a course saved under a
    # longer one, so the timetable and the deadline list agree on one course.
    long_code_course = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1", title="Models of Computation")
    conn = db.connect(":memory:")
    db.save(conn, [long_code_course], meetings=[LECTURE])
    assert db.schedule(conn)[0][0] == "CPSC 121"
