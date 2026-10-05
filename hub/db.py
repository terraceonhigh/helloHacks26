"""One SQLite file, normalised tables (Terrace's storage proposal, Agent board #15).

`courses` organizes everything; `items` holds every task/deadline/material
from any adapter, tagged by `category` (see hub.models.CATEGORY_FOR).
Textbooks get their own table since they carry ISBN/price, not a due date.

# ponytail: no raw-per-provider tables yet. Add them (one JSON blob table
# per source) only if we actually need to re-normalise without refetching -
# right now every adapter is cheap enough to just re-fetch.
"""
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import timezone
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

-- A recurring weekly class meeting (hub.models.Meeting) - no due date, no
-- url, so no (source, url) identity like items has. days/start_time/
-- term_start/term_end together with course+kind+source are the closest
-- real-world identity a re-import can match against: the same lecture
-- re-exported next week must update in place, not duplicate.
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id),
    kind TEXT NOT NULL,
    days TEXT NOT NULL,  -- comma-joined ISO weekday codes, e.g. "MO,WE,FR"
    start_time TEXT NOT NULL,  -- "HH:MM", 24h, naive (always America/Vancouver - see hub.models.Meeting)
    end_time TEXT NOT NULL,
    location TEXT NOT NULL,
    term_start TEXT NOT NULL,  -- "YYYY-MM-DD"
    term_end TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(course_id, kind, days, start_time, term_start, source)
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


def save(conn, courses=(), items=(), textbooks=(), meetings=()):
    """Upsert courses, then items/textbooks/meetings matched to them by
    canonical course code (see _canonical_code) - collapses Canvas's long
    code, Workday's short one and PrairieLearn's onto the same course row."""
    if isinstance(conn, Hosted):
        return _hosted_save(conn, courses, items)
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
    for m in meetings:
        cid = ids.get(_canonical_code(m.course))
        if cid is None:
            continue  # no matching course this call; skip rather than orphan the row
        conn.execute(
            "INSERT INTO meetings (course_id, kind, days, start_time, end_time, location, term_start, term_end, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(course_id, kind, days, start_time, term_start, source) DO UPDATE SET "
            "end_time=excluded.end_time, location=excluded.location, term_end=excluded.term_end",
            (cid, m.kind, ",".join(m.days), m.start_time.isoformat(), m.end_time.isoformat(),
             m.location, m.term_start.isoformat(), m.term_end.isoformat(), m.source),
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
    if isinstance(conn, Hosted):
        return _hosted_upcoming(conn, category)
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
    if isinstance(conn, Hosted):
        raise NotImplementedError("hosted store has no undated() yet - see the Hosted ponytail below")
    q = ("SELECT courses.code, items.category, items.kind, items.title, items.due, items.url, items.done, items.source "
         "FROM items JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.id DESC")
    return conn.execute(q, (category,) if category else ()).fetchall()


def courses(conn):
    """Every course, e.g. for a Courses / Course-card screen."""
    if isinstance(conn, Hosted):
        return conn.run("SELECT code, term, title, grade FROM hosted_courses WHERE student = ? ORDER BY code",
                        (conn.student,)).fetchall()
    return conn.execute("SELECT code, term, title, grade FROM courses ORDER BY code").fetchall()


def by_course(conn, category=None):
    """upcoming(), grouped under each course code - what a Course card wants:
    "this course's" tasks/deadlines/materials, each list still soonest-first."""
    grouped = {}
    for row in upcoming(conn, category):
        grouped.setdefault(row[0], []).append(row)
    return grouped


def textbooks(conn, code=None):
    """Every textbook, joined to its course code - optionally for just one
    course. Row shape: (course_code, title, isbn, required, price, url).
    Required books first, since that's what a student actually needs to buy."""
    q = ("SELECT courses.code, textbooks.title, textbooks.isbn, textbooks.required, "
         "textbooks.price, textbooks.url FROM textbooks JOIN courses ON courses.id = textbooks.course_id"
         + (" WHERE courses.code = ?" if code else "") + " ORDER BY textbooks.required DESC, textbooks.title")
    return conn.execute(q, (code,) if code else ()).fetchall()


# --- Hosted store (web/api/sync.py, items.py) ------------------------------
# Same public API as above (save / upcoming / by_course / courses, plus
# wipe), but against hosted Postgres (Neon) and scoped to one `student` -
# sha256 of the client's sync key (hub/hosted.py), never the key itself.
# Pass a Hosted from connect_hosted() where you'd pass a sqlite3 connection
# and the functions above dispatch here. Kept in this file (not a separate
# pgstore.py) so "nothing else touches SQL" stays literally true.
#
# The SQL is deliberately portable (CREATE TABLE IF NOT EXISTS, ON CONFLICT
# ... DO UPDATE, excluded.*, no serial ids) so tests run it against an
# in-memory SQLite connection wrapped in Hosted(conn, student, "?") - no
# Postgres needed. psycopg only differs in its placeholder, "%s".
#
# ponytail: no textbooks, no undated() - the extension's normalized body
# (web/api/sync.py) carries only courses and items. Add a hosted_textbooks
# table when a hosted Bookstore sync exists.
# ponytail: upsert only - an item deleted upstream lingers until the
# student DELETEs /api/sync. Upgrade: delete this student's rows for a
# source that aren't in a fresh full sync of it.

HOSTED_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS hosted_courses (
        student TEXT NOT NULL,
        code TEXT NOT NULL,
        term TEXT NOT NULL,
        title TEXT NOT NULL,
        grade REAL,
        PRIMARY KEY (student, code, term)
    )""",
    """CREATE TABLE IF NOT EXISTS hosted_items (
        student TEXT NOT NULL,
        source TEXT NOT NULL,
        url TEXT NOT NULL,
        course TEXT NOT NULL,
        category TEXT NOT NULL CHECK (category IN ('task', 'deadline', 'material')),
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        due TEXT,
        done INTEGER,
        PRIMARY KEY (student, source, url)
    )""",
)


@dataclass
class Hosted:
    conn: object  # a psycopg (or, in tests, sqlite3) connection
    student: str
    placeholder: str = "%s"

    def run(self, sql, params=()):
        return self.conn.execute(sql.replace("?", self.placeholder), params)

    def close(self):
        self.conn.close()


def hosted_url():
    """The Postgres URL, or None when hosted storage isn't provisioned -
    web/api's routes then answer 503 instead of touching anything."""
    return os.environ.get("DATABASE_URL") or None


def connect_hosted(student, url=None):
    import psycopg  # only web/api/requirements.txt has it; local SQLite never needs it

    return init_hosted(Hosted(psycopg.connect(url or hosted_url()), student))


def init_hosted(h):
    for ddl in HOSTED_SCHEMA:
        h.run(ddl)
    h.conn.commit()
    return h


def _hosted_save(h, courses, items):
    for c in courses:
        # Same merge rules as _course_id's #41 comment: shorter title wins,
        # a known grade survives an unknown one.
        h.run(
            "INSERT INTO hosted_courses (student, code, term, title, grade) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (student, code, term) DO UPDATE SET "
            "title=CASE WHEN length(excluded.title) < length(hosted_courses.title) "
            "THEN excluded.title ELSE hosted_courses.title END, "
            "grade=COALESCE(excluded.grade, hosted_courses.grade)",
            (h.student, _canonical_code(c.code), _canonical_term(c.term), c.title, c.grade),
        )
    for i in items:
        # UTC before storing, so ORDER BY due on the ISO text is chronological.
        due = i.due.astimezone(timezone.utc).isoformat() if i.due else None
        h.run(
            "INSERT INTO hosted_items (student, source, url, course, category, kind, title, due, done) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (student, source, url) DO UPDATE SET course=excluded.course, "
            "category=excluded.category, kind=excluded.kind, title=excluded.title, "
            "due=excluded.due, done=excluded.done",
            (h.student, i.source, i.url, _canonical_code(i.course), i.category, i.kind, i.title,
             due, None if i.done is None else int(i.done)),
        )
    h.conn.commit()


def _hosted_upcoming(h, category=None):
    q = ("SELECT course, category, kind, title, due, url, done, source FROM hosted_items "
         "WHERE student = ? AND due IS NOT NULL" + (" AND category = ?" if category else "") +
         " ORDER BY due")
    return h.run(q, (h.student, category) if category else (h.student,)).fetchall()


def wipe(h):
    """Delete every row this student has - DELETE /api/sync."""
    h.run("DELETE FROM hosted_items WHERE student = ?", (h.student,))
    h.run("DELETE FROM hosted_courses WHERE student = ?", (h.student,))
    h.conn.commit()


def schedule(conn):
    """Every recurring class meeting, joined to its course code. Row shape:
    (code, kind, days, start_time, end_time, location, term_start, term_end,
    source) - days/times/dates as stored (comma-joined codes, "HH:MM",
    "YYYY-MM-DD" text); hub.models.Meeting reconstructs typed values if
    needed, same division of labour as upcoming()'s rows. Ordered by course
    then start time - a natural read order for a weekly-timetable view."""
    return conn.execute(
        "SELECT courses.code, meetings.kind, meetings.days, meetings.start_time, meetings.end_time, "
        "meetings.location, meetings.term_start, meetings.term_end, meetings.source "
        "FROM meetings JOIN courses ON courses.id = meetings.course_id "
        "ORDER BY courses.code, meetings.start_time"
    ).fetchall()
