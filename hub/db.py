"""One SQLite file, normalised tables (Terrace's storage proposal, Agent board #15).

`courses` organizes everything; `items` holds every task/deadline/material
from any adapter, tagged by `category` (see hub.models.CATEGORY_FOR).
Textbooks get their own table since they carry ISBN/price, not a due date.

# ponytail: no raw-per-provider tables yet. Add them (one JSON blob table
# per source) only if we actually need to re-normalise without refetching -
# right now every adapter is cheap enough to just re-fetch.
"""
import re
import sqlite3
from pathlib import Path

from hub.logic import normalise_course_code

PATH = Path.home() / ".ubc-hub" / "hub.db"


def _canonical_code(code):
    """"CPSC 121", "CPSC 121 101 2026W1" and "cpsc121" all name the same
    course - collapse every code to "FACULTY NUMBER" (section dropped: it's
    schedule/clash data, not part of course identity) so Canvas's long code
    and Workday's short one land on the same course row. Falls back to the
    raw text when it doesn't parse, rather than silently dropping the
    course."""
    faculty, number, _section = normalise_course_code(code)
    return f"{faculty} {number}" if faculty and number else code


def _canonical_term(term):
    """Canvas's "2026 Winter Term 1" and Workday's "2026W1" name the same
    term - collapse to the short UBC form. "" stays "" (= unknown)."""
    # ponytail: only UBC's "<year> Winter|Summer Term <n>" spelling is mapped;
    # anything else is kept as-is. Add a pattern when a new source needs one.
    term = (term or "").strip()  # Canvas can send term.name: null
    m = re.fullmatch(r"(\d{4})\s+(Winter|Summer)\s+Term\s+(\d)", term, re.I)
    return f"{m[1]}{m[2][0].upper()}{m[3]}" if m else term


# ponytail: no migration for a hub.db that predates canonical course codes -
# it's a hackathon demo, not a production rollout with real users' existing
# data at stake. A pre-existing course row keeps its old raw code (e.g.
# "CPSC 121 101 2026W1") until it's re-saved, so it can sit alongside a new
# canonical row for the same real course. Delete ~/.ubc-hub/hub.db after
# pulling this change; upgrade to a real migration if that ever isn't fine.

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
    # CREATE TABLE IF NOT EXISTS doesn't add columns to a table that already
    # exists - a hub.db from before `done` landed would crash on it (#27,
    # #21) with "no such column: items.done". Guarded, so this is a no-op
    # once every db has the column.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    if "done" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN done INTEGER")
    return conn


def _course_id(conn, course):
    code, term = _canonical_code(course.code), _canonical_term(course.term)
    if not term:
        # Unknown term: attach to an existing row for this code, if any.
        # ponytail: if the same code exists under several real terms (a
        # retake), this picks one arbitrarily; fine until we store history.
        row = conn.execute("SELECT id FROM courses WHERE code=? ORDER BY term = '' LIMIT 1", (code,)).fetchone()
        if row:
            conn.execute(
                "UPDATE courses SET title=CASE WHEN length(?) < length(title) THEN ? ELSE title END, "
                "grade=COALESCE(?, grade) WHERE id=?",
                (course.title, course.title, course.grade, row[0]),
            )
            return row[0]
    else:
        # A row saved earlier with an unknown term takes the real one now.
        conn.execute("UPDATE courses SET term=? WHERE code=? AND term='' AND NOT EXISTS "
                     "(SELECT 1 FROM courses WHERE code=? AND term=?)", (term, code, code, term))
    # #41: a lecture and its lab shell canonicalise to one course row, so
    # whichever is saved last must not blindly win. Grade: a known value
    # survives an unknown one (COALESCE); when both are known, last wins -
    # a separate question this doesn't decide. Title: shorter wins, on the
    # (UBC) assumption that the lab shell's title, if it differs at all, is
    # the lecture's with a suffix like "(Lab)" tacked on.
    # ponytail: content-based, not source-based - revisit if a real account
    # shows the lecture shell with the longer title.
    conn.execute(
        "INSERT INTO courses (code, term, title, grade) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(code, term) DO UPDATE SET "
        "title=CASE WHEN length(excluded.title) < length(courses.title) THEN excluded.title ELSE courses.title END, "
        "grade=COALESCE(excluded.grade, grade)",
        (code, term, course.title, course.grade),
    )
    row = conn.execute("SELECT id FROM courses WHERE code=? AND term=?", (code, term)).fetchone()
    return row[0]


def save(conn, courses=(), items=(), textbooks=()):
    """Upsert courses, then items/textbooks matched to them by canonical
    course code (see _canonical_code) - collapses Canvas's long code,
    Workday's short one and PrairieLearn's onto the same course row."""
    ids = {_canonical_code(c.code): _course_id(conn, c) for c in courses}
    for i in items:
        conn.execute(
            "INSERT INTO items (course_id, category, kind, title, due, url, source, done) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, url) DO UPDATE SET course_id=COALESCE(excluded.course_id, course_id), category=excluded.category, kind=excluded.kind, "
            "title=excluded.title, due=excluded.due, done=excluded.done",
            (ids.get(_canonical_code(i.course)), i.category, i.kind, i.title,
             i.due.isoformat() if i.due else None, i.url, i.source,
             None if i.done is None else int(i.done)),
        )
    for t in textbooks:
        cid = ids.get(_canonical_code(t.course))
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
    Row shape: (code, category, kind, title, due, url, done, source). `done`
    is 0/1/None as stored - build a Status ("overdue"/"soon"/...) from it and
    `due` with hub.models.status_of, don't recompute the logic here. `source`
    is appended last so existing positional access (row[6] for `done`, etc.)
    stays valid.

    LEFT JOIN, not JOIN: an item whose course didn't resolve at save() time
    (e.g. Canvas connected before any course-giving source has run) must
    still show up here - an INNER JOIN would silently vanish it instead of
    just showing an unknown course, and "always produce something useful,
    never refuse on partial data" is this repo's own stated rule."""
    q = ("SELECT COALESCE(courses.code, '(unknown course)'), items.category, items.kind, items.title, "
         "items.due, items.url, items.done, items.source "
         "FROM items LEFT JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NOT NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.due")
    return conn.execute(q, (category,) if category else ()).fetchall()


def undated(conn, category=None):
    """Items with no due date - a running feed (announcements, and anything
    else without a real deadline) kept separate from upcoming()'s ranked
    list, since there's nothing to rank by. Most recently saved first. Same
    row shape as upcoming(), `due` just always reads NULL here."""
    q = ("SELECT courses.code, items.category, items.kind, items.title, items.due, items.url, items.done, items.source "
         "FROM items JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.id DESC")
    return conn.execute(q, (category,) if category else ()).fetchall()


def courses(conn):
    """Every course, e.g. for a Courses / Course-card screen."""
    return conn.execute("SELECT code, term, title, grade FROM courses ORDER BY code").fetchall()


def textbooks(conn):
    """Every textbook, joined to its course code. Row shape: (code, title,
    isbn, required, price, url). LEFT JOIN for the same reason as upcoming():
    a textbook whose course didn't resolve at save() time shouldn't vanish."""
    q = ("SELECT COALESCE(courses.code, '(unknown course)'), textbooks.title, textbooks.isbn, "
         "textbooks.required, textbooks.price, textbooks.url "
         "FROM textbooks LEFT JOIN courses ON courses.id = textbooks.course_id "
         "ORDER BY courses.code, textbooks.title")
    return conn.execute(q).fetchall()


def by_course(conn, category=None):
    """upcoming(), grouped under each course code - what a Course card wants:
    "this course's" tasks/deadlines/materials, each list still soonest-first."""
    grouped = {}
    for row in upcoming(conn, category):
        grouped.setdefault(row[0], []).append(row)
    return grouped
