"""main's tests/test_db.py + test_db_oracle_pr33.py semantics, on lauds.store."""
import os
import sqlite3
import stat
from datetime import date, datetime, time, timedelta, timezone

import pytest

from lauds import store
from lauds.models import Bundle, Course, Item, Meeting, Textbook

UTC = timezone.utc
PDT = timezone(timedelta(hours=-7))
COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation", grade=88.5)
OTHER = Course(code="ENGL 112", section="", term="2026W1", title="Strategies for University Writing")
QUIZ = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
            due=datetime(2026, 9, 30, 6, 59, tzinfo=UTC), url="https://x/q/1", source="canvas")
BOOK = Textbook(course="CPSC 121", title="Discrete Math", isbn="123", required=True, price=80.0, url="https://x/b/1")


def mk(**kw):
    return Item(**{**QUIZ.__dict__, **kw})


@pytest.fixture
def conn():
    return store.connect(":memory:")


def test_save_and_upcoming(conn):
    store.save(conn, [COURSE], [QUIZ], [BOOK])
    rows = store.upcoming(conn)
    assert rows[0][:8] == ("CPSC 121", "deadline", "quiz", "Quiz 2", "2026-09-30T06:59:00+00:00",
                           "https://x/q/1", None, "canvas")
    assert isinstance(rows[0][8], int)  # lauds: item id appended


def test_done_round_trips(conn):
    store.save(conn, [COURSE], [mk(done=True)])
    assert store.upcoming(conn)[0][6] == 1


def test_save_is_idempotent_and_updates(conn):
    store.save(conn, [COURSE], [QUIZ])
    store.save(conn, [COURSE], [mk(title="Quiz 2 (rescheduled)")])
    rows = store.upcoming(conn)
    assert len(rows) == 1 and rows[0][3] == "Quiz 2 (rescheduled)"


def test_upcoming_filters_by_category(conn):
    reading = mk(category="material", kind="reading", title="Ch. 3", url="https://x/r/1")
    store.save(conn, [COURSE], [QUIZ, reading])
    assert [r[2] for r in store.upcoming(conn, category="deadline")] == ["quiz"]
    assert [r[2] for r in store.upcoming(conn, category="material")] == ["reading"]


def test_upcoming_sorts_by_instant_across_offsets(conn):
    early = mk(url="https://x/1", title="early", due=datetime(2026, 10, 1, 20, 0, tzinfo=PDT))  # 03:00Z Oct 2
    late = mk(url="https://x/2", title="late", due=datetime(2026, 10, 2, 4, 0, tzinfo=UTC))
    store.save(conn, [COURSE], [late, early])
    assert [r[3] for r in store.upcoming(conn)] == ["early", "late"]


def test_undated_separate_and_newest_first(conn):
    a1 = mk(kind="announcement", category="task", title="First", due=None, url="https://x/a/1")
    a2 = mk(kind="announcement", category="task", title="Second", due=None, url="https://x/a/2")
    store.save(conn, [COURSE], [QUIZ, a1])
    store.save(conn, [COURSE], [a2])
    assert [r[3] for r in store.upcoming(conn)] == ["Quiz 2"]
    assert [r[3] for r in store.undated(conn)] == ["Second", "First"]


def test_courses_and_by_course(conn):
    essay = mk(course="ENGL 112", kind="assignment", category="task", title="Essay 1", url="https://x/e/1",
               due=datetime(2026, 10, 1, tzinfo=UTC))
    store.save(conn, [COURSE, OTHER], [QUIZ, essay])
    assert [c[0] for c in store.courses(conn)] == ["CPSC 121", "ENGL 112"]
    g = store.by_course(conn)
    assert [r[3] for r in g["CPSC 121"]] == ["Quiz 2"] and [r[3] for r in g["ENGL 112"]] == ["Essay 1"]


def test_textbooks_required_first_and_filter(conn):
    opt = Textbook(course="CPSC 121", title="Companion Reader", isbn="999", required=False, price=None, url="")
    other = Textbook(course="ENGL 112", title="Style Guide", isbn="456", required=True, price=40.0, url="u")
    store.save(conn, [COURSE, OTHER], [], [opt, BOOK, other])
    rows = store.textbooks(conn, "CPSC 121")
    assert [r[1] for r in rows] == ["Discrete Math", "Companion Reader"]
    assert rows[0] == ("CPSC 121", "Discrete Math", "123", True, 80.0, "https://x/b/1")
    assert [r[0] for r in store.textbooks(conn, "cpsc121")] == ["CPSC 121", "CPSC 121"]


def test_textbook_without_course_this_call_is_skipped(conn):
    store.save(conn, [], [], [BOOK])
    assert store.textbooks(conn) == []


def test_long_and_short_codes_join_one_course(conn):
    wd = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")
    it = mk(course="CPSC 121 101 2026W1", url="https://canvas/1")
    store.save(conn, [wd], [it])
    assert [c[0] for c in store.courses(conn)] == ["CPSC 121"]
    assert store.upcoming(conn)[0][0] == "CPSC 121"


def test_unmatched_course_still_shows(conn):
    store.save(conn, [], [mk(course="PHIL 100", url="https://x/orphan")])
    assert store.upcoming(conn)[0][0] == "(unknown course)"


def test_item_keeps_course_link_when_resaved_without_course(conn):
    store.save(conn, [COURSE], [QUIZ])
    store.save(conn, [], [mk(title="again")])
    assert store.upcoming(conn)[0][0] == "CPSC 121"


def test_term_spellings_are_one_row(conn):
    store.save(conn, [Course(code="CPSC 121", section="", term="", title="CPSC 121")])
    store.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026 Winter Term 1",
                             title="Models of Computation", grade=84.0)])
    store.save(conn, [Course(code="CPSC 121", section="101", term="2026W1", title="Models of Computation")])
    assert store.courses(conn) == [("CPSC 121", "2026W1", "CPSC 121", 84.0)]


def test_lab_shell_keeps_grade_and_shorter_title(conn):
    store.save(conn, [Course("CPSC 121 101 2026W1", "101", "2026W1", "Models of Computation", 84.0)])
    store.save(conn, [Course("CPSC 121 L1A 2026W1", "L1A", "2026W1", "Models of Computation (Lab)", None)])
    assert store.courses(conn) == [("CPSC 121", "2026W1", "Models of Computation", 84.0)]


def test_schedule_and_meeting_upsert(conn):
    m = Meeting("CPSC 121", "lecture", ["MO", "WE", "FR"], time(9), time(10), "DMP 110",
                date(2026, 9, 8), date(2026, 12, 4), "workday")
    store.save(conn, [COURSE], meetings=[m])
    store.save(conn, [COURSE], meetings=[Meeting(**{**m.__dict__, "location": "DMP 310"})])
    assert store.schedule(conn) == [("CPSC 121", "lecture", "MO,WE,FR", "09:00:00", "10:00:00", "DMP 310",
                                     "2026-09-08", "2026-12-04", "workday")]


def test_get_item_and_lauds_fields(conn):
    store.save_bundle(conn, Bundle(courses=[COURSE], items=[mk(description="d", points=5.0, extra={"a": 1})]))
    iid = store.upcoming(conn)[0][8]
    got = store.get_item(conn, iid)
    assert (got["course"], got["title"], got["description"], got["points"], got["extra"], got["files"],
            got["done"], got["course_raw"]) == ("CPSC 121", "Quiz 2", "d", 5.0, {"a": 1}, [], None, "CPSC 121")
    assert store.get_item(conn, 99999) is None


def test_sync_status(conn):
    t1 = datetime(2026, 9, 28, 9, tzinfo=UTC)
    store.record_sync(conn, "canvas", True, {"items": 3}, at=t1)
    store.record_sync(conn, "canvas", False, error="boom", at=t1 + timedelta(hours=1))
    [(src, attempt, success, ok, counts, err)] = store.sync_status(conn)
    assert (src, ok, counts, err) == ("canvas", False, {"items": 3}, "boom")
    assert success == t1.isoformat() and attempt > success


def test_file_db_under_lauds_home_is_private_and_readonly_works(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path / "home"))
    c = store.connect()
    store.save(c, [COURSE], [QUIZ])
    c.close()
    db = tmp_path / "home" / "lauds.db"
    assert db.exists()
    if os.name == "posix" and stat.S_IMODE(db.stat().st_mode) != 0o660:  # /sdcard ignores modes
        assert stat.S_IMODE(db.stat().st_mode) == 0o600
    ro = store.connect_readonly()
    assert ro.execute("SELECT count(*) FROM items").fetchone() == (1,)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM items")
