from datetime import datetime

from hub import db
from hub.models import Course, Item, Textbook

COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation", grade=88.5)
OTHER_COURSE = Course(code="ENGL 112", section="", term="2026W1", title="Strategies for University Writing")
QUIZ = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
            due=datetime(2026, 9, 30, 6, 59), url="https://x/q/1", source="canvas")
BOOK = Textbook(course="CPSC 121", title="Discrete Math", isbn="123", required=True, price=80.0, url="https://x/b/1")


def test_save_and_upcoming():
    conn = db.connect(":memory:")
    db.save(conn, [COURSE], [QUIZ], [BOOK])
    rows = db.upcoming(conn)
    assert rows == [("CPSC 121", "deadline", "quiz", "Quiz 2", "2026-09-30T06:59:00", "https://x/q/1", None, "canvas")]
    assert conn.execute("SELECT isbn FROM textbooks").fetchall() == [("123",)]


def test_done_round_trips_through_sqlite():
    conn = db.connect(":memory:")
    done_item = Item(**{**QUIZ.__dict__, "done": True})
    db.save(conn, [COURSE], [done_item])
    assert db.upcoming(conn)[0][6] is True or db.upcoming(conn)[0][6] == 1  # sqlite has no real bool


def test_save_is_idempotent_and_updates():
    conn = db.connect(":memory:")
    db.save(conn, [COURSE], [QUIZ])
    updated = Item(**{**QUIZ.__dict__, "title": "Quiz 2 (rescheduled)"})
    db.save(conn, [COURSE], [updated])
    rows = db.upcoming(conn)
    assert len(rows) == 1  # same (source, url) -> updated in place, not duplicated
    assert rows[0][3] == "Quiz 2 (rescheduled)"


def test_upcoming_filters_by_category():
    conn = db.connect(":memory:")
    reading = Item(course="CPSC 121", category="material", kind="reading", title="Ch. 3",
                    due=datetime(2026, 9, 29), url="https://x/r/1", source="canvas")
    db.save(conn, [COURSE], [QUIZ, reading])
    assert [r[2] for r in db.upcoming(conn, category="deadline")] == ["quiz"]
    assert [r[2] for r in db.upcoming(conn, category="material")] == ["reading"]


def test_undated_holds_items_with_no_due_date_separately_from_upcoming():
    conn = db.connect(":memory:")
    announcement = Item(course="CPSC 121", category="task", kind="announcement", title="Welcome!",
                         due=None, url="https://x/a/1", source="canvas")
    db.save(conn, [COURSE], [QUIZ, announcement])
    assert [r[3] for r in db.upcoming(conn)] == ["Quiz 2"]  # undated item never shows up here
    assert [r[3] for r in db.undated(conn)] == ["Welcome!"]


def test_undated_is_most_recently_saved_first():
    conn = db.connect(":memory:")
    first = Item(course="CPSC 121", category="task", kind="announcement", title="First",
                 due=None, url="https://x/a/1", source="canvas")
    second = Item(course="CPSC 121", category="task", kind="announcement", title="Second",
                  due=None, url="https://x/a/2", source="canvas")
    db.save(conn, [COURSE], [first])
    db.save(conn, [COURSE], [second])  # a later, separate fetch - not re-saving `first`
    assert [r[3] for r in db.undated(conn)] == ["Second", "First"]


def test_courses_and_by_course_grouping():
    conn = db.connect(":memory:")
    essay = Item(course="ENGL 112", category="task", kind="assignment", title="Essay 1",
                 due=datetime(2026, 10, 1), url="https://x/e/1", source="canvas")
    db.save(conn, [COURSE, OTHER_COURSE], [QUIZ, essay])
    assert [c[0] for c in db.courses(conn)] == ["CPSC 121", "ENGL 112"]  # alphabetical, both present even though ENGL's item comes later
    grouped = db.by_course(conn)
    assert set(grouped) == {"CPSC 121", "ENGL 112"}
    assert [row[3] for row in grouped["CPSC 121"]] == ["Quiz 2"]
    assert [row[3] for row in grouped["ENGL 112"]] == ["Essay 1"]


def test_textbooks_joins_course_code_and_orders_required_first():
    conn = db.connect(":memory:")
    optional_book = Textbook(course="CPSC 121", title="Companion Reader", isbn="999",
                              required=False, price=None, url="")
    db.save(conn, [COURSE], [], [optional_book, BOOK])
    rows = db.textbooks(conn)
    assert [r[1] for r in rows] == ["Discrete Math", "Companion Reader"]  # required first
    assert rows[0] == ("CPSC 121", "Discrete Math", "123", True, 80.0, "https://x/b/1")


def test_textbooks_filters_by_course_code():
    conn = db.connect(":memory:")
    other_book = Textbook(course="ENGL 112", title="Style Guide", isbn="456",
                           required=True, price=40.0, url="https://x/b/2")
    db.save(conn, [COURSE, OTHER_COURSE], [], [BOOK, other_book])
    assert [r[0] for r in db.textbooks(conn, "CPSC 121")] == ["CPSC 121"]


def test_canvas_long_code_joins_the_same_course_as_workday_short_code():
    conn = db.connect(":memory:")
    workday_course = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")
    canvas_item = Item(course="CPSC 121 101 2026W1", category="task", kind="assignment", title="PS3",
                        due=datetime(2026, 9, 28), url="https://canvas/1", source="canvas")
    db.save(conn, [workday_course], [canvas_item])
    assert [c[0] for c in db.courses(conn)] == ["CPSC 121"]  # one course, not two
    rows = db.upcoming(conn)
    assert rows == [("CPSC 121", "task", "assignment", "PS3", "2026-09-28T00:00:00", "https://canvas/1", None, "canvas")]


def test_item_with_unmatched_course_still_shows_up():
    conn = db.connect(":memory:")
    orphan = Item(course="PHIL 100", category="task", kind="assignment", title="Essay",
                  due=datetime(2026, 9, 28), url="https://x/orphan", source="canvas")
    db.save(conn, [], [orphan])  # no matching course this call
    rows = db.upcoming(conn)
    assert len(rows) == 1  # never silently dropped by the course join
    assert rows[0][0] == "(unknown course)"
    assert rows[0][3] == "Essay"


def test_connect_migrates_a_db_from_before_done_existed(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE courses (id INTEGER PRIMARY KEY, code TEXT NOT NULL, term TEXT NOT NULL,
                               title TEXT NOT NULL, grade REAL, UNIQUE(code, term));
        CREATE TABLE items (id INTEGER PRIMARY KEY, course_id INTEGER, category TEXT NOT NULL,
                             kind TEXT NOT NULL, title TEXT NOT NULL, due TEXT, url TEXT NOT NULL,
                             source TEXT NOT NULL, UNIQUE(source, url));
        CREATE TABLE textbooks (id INTEGER PRIMARY KEY, course_id INTEGER, title TEXT NOT NULL,
                                 isbn TEXT NOT NULL, required INTEGER NOT NULL, price REAL,
                                 url TEXT NOT NULL, UNIQUE(course_id, isbn));
    """)  # schema exactly as it was before `done` (pre-#27), on a real file, not sample data
    legacy.execute("INSERT INTO courses (code, term, title) VALUES ('CPSC 121', '2026W1', 'x')")
    legacy.execute("INSERT INTO items (course_id, category, kind, title, due, url, source) "
                    "VALUES (1, 'task', 'assignment', 'old row', '2026-01-01T00:00:00', 'https://x', 'canvas')")
    legacy.commit()
    legacy.close()

    conn = db.connect(path)  # this used to raise "no such column: items.done" (#21, #27)
    rows = db.upcoming(conn)
    assert rows[0][3] == "old row"
    assert rows[0][6] is None
