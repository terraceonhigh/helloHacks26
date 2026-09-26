"""One SQLite file, normalised tables (Terrace's storage proposal, Agent board #15).

`courses` organizes everything; `items` holds every task/deadline/material
from any adapter, tagged by `category` (see hub.models.CATEGORY_FOR).
Textbooks get their own table since they carry ISBN/price, not a due date.

# ponytail: no raw-per-provider tables yet. Add them (one JSON blob table
# per source) only if we actually need to re-normalise without refetching -
# right now every adapter is cheap enough to just re-fetch.
"""
import sqlite3
from pathlib import Path

PATH = Path.home() / ".ubc-hub" / "hub.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    term TEXT NOT NULL,
    title TEXT NOT NULL,
    grade REAL,
    UNIQUE(code, term)
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id),
    category TEXT NOT NULL CHECK (category IN ('task', 'deadline', 'material')),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    due TEXT,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    done INTEGER,  -- NULL = unknown/not applicable; 0/1 otherwise. "overdue"/"soon" are never stored - see hub.models.status_of
    UNIQUE(source, url)
);

CREATE TABLE IF NOT EXISTS textbooks (
    id INTEGER PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id),
    title TEXT NOT NULL,
    isbn TEXT NOT NULL,
    required INTEGER NOT NULL,
    price REAL,
    url TEXT NOT NULL,
    UNIQUE(course_id, isbn)
);
"""


def connect(path=PATH):
    if path != ":memory:":
        path.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def _course_id(conn, course):
    conn.execute(
        "INSERT INTO courses (code, term, title, grade) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(code, term) DO UPDATE SET title=excluded.title, grade=excluded.grade",
        (course.code, course.term, course.title, course.grade),
    )
    row = conn.execute("SELECT id FROM courses WHERE code=? AND term=?", (course.code, course.term)).fetchone()
    return row[0]


def save(conn, courses=(), items=(), textbooks=()):
    """Upsert courses, then items/textbooks matched to them by course code.

    # ponytail: text match on course code, not Sam's fuzzy course_key (#2).
    # Fine while every item so far comes straight from Canvas, whose own
    # items already agree with its own course codes; revisit once a second
    # source (Workday, PrairieLearn) needs joining onto the same course.
    """
    ids = {c.code: _course_id(conn, c) for c in courses}
    for i in items:
        conn.execute(
            "INSERT INTO items (course_id, category, kind, title, due, url, source, done) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, url) DO UPDATE SET category=excluded.category, kind=excluded.kind, "
            "title=excluded.title, due=excluded.due, done=excluded.done",
            (ids.get(i.course), i.category, i.kind, i.title, i.due.isoformat() if i.due else None, i.url, i.source,
             None if i.done is None else int(i.done)),
        )
    for t in textbooks:
        cid = ids.get(t.course)
        if cid is None:
            continue  # no matching course this call; skip rather than orphan the row
        conn.execute(
            "INSERT INTO textbooks (course_id, title, isbn, required, price, url) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(course_id, isbn) DO UPDATE SET title=excluded.title, required=excluded.required, "
            "price=excluded.price, url=excluded.url",
            (cid, t.title, t.isbn, int(t.required), t.price, t.url),
        )
    conn.commit()


def upcoming(conn, category=None):
    """Items with a due date, soonest first, joined to their course code.
    `category` filters to just "task"/"deadline"/"material" if given.
    Row shape: (code, category, kind, title, due, url, done). `done` is
    0/1/None as stored - build a Status ("overdue"/"soon"/...) from it and
    `due` with hub.models.status_of, don't recompute the logic here."""
    q = ("SELECT courses.code, items.category, items.kind, items.title, items.due, items.url, items.done "
         "FROM items JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NOT NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.due")
    return conn.execute(q, (category,) if category else ()).fetchall()


def courses(conn):
    """Every course, e.g. for a Courses / Course-card screen."""
    return conn.execute("SELECT code, term, title, grade FROM courses ORDER BY code").fetchall()


def by_course(conn, category=None):
    """upcoming(), grouped under each course code - what a Course card wants:
    "this course's" tasks/deadlines/materials, each list still soonest-first."""
    grouped = {}
    for row in upcoming(conn, category):
        grouped.setdefault(row[0], []).append(row)
    return grouped
