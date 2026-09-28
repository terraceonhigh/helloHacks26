"""Minimal SQLite store: only what the CLI needs.

The database design is on hold (BRIEF.md), so this mirrors main's hub/db.py
schema and query semantics - canonical course codes and terms, (source, url)
upsert for items, the lecture/lab title-and-grade merge - plus a small
`sync_status` table and a few lauds-only item columns.

Query row shapes are main's, with lauds-only columns appended at the END so
positional access and the parity comparator (which reads only the oracle's
positions) keep working:

  upcoming/undated: (code, category, kind, title, due, url, done, source, id)
  courses:          (code, term, title, grade)
  textbooks:        (code, title, isbn, required, price, url)
  schedule:         (code, kind, days, start_time, end_time, location,
                     term_start, term_end, source)
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lauds import paths
from lauds.compat import jsonable
from lauds.models import Bundle, canonical_code as _canonical_code, canonical_term as _canonical_term

# ponytail: no migrations - a new schema means deleting lauds.db and
# re-syncing (every adapter is cheap to re-fetch). Add a schema_version table
# and real migrations once the DB design lands.
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
    due TEXT,           -- ISO 8601 as the adapter gave it (offset kept)
    due_utc TEXT,       -- same instant in UTC, for chronological ORDER BY
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    done INTEGER,       -- NULL = unknown; 0/1. overdue/soon are never stored - see models.status_of
    course_raw TEXT,    -- the course string the adapter sent, before canonicalising
    description TEXT,
    points REAL,
    files TEXT,         -- JSON list of ItemFile dicts
    extra TEXT,         -- JSON object
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

-- Recurring weekly class meetings: no url, so course+kind+days+start_time+
-- term_start+source is the identity a re-import matches against.
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id),
    kind TEXT NOT NULL,
    days TEXT NOT NULL,        -- comma-joined ISO weekday codes, "MO,WE,FR"
    start_time TEXT NOT NULL,  -- naive "HH:MM[:SS]", America/Vancouver
    end_time TEXT NOT NULL,
    location TEXT NOT NULL,
    term_start TEXT NOT NULL,  -- "YYYY-MM-DD"
    term_end TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(course_id, kind, days, start_time, term_start, source)
);

CREATE TABLE IF NOT EXISTS sync_status (
    source TEXT PRIMARY KEY,
    last_attempt TEXT NOT NULL,   -- ISO 8601 UTC
    last_success TEXT,
    ok INTEGER NOT NULL,
    counts TEXT,                  -- JSON {"items": n, ...} of the last success
    error TEXT
);
"""


def connect(path=None):
    """Open (creating if needed) the store. `path=":memory:"` for tests."""
    if path is None:
        path = paths.db_path()
    if path != ":memory:":
        path = Path(path)
        paths.ensure_dir(path.parent)
        new = not path.exists()
    conn = sqlite3.connect(path if path == ":memory:" else str(path))
    if path != ":memory:" and new:
        paths.secure_file(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def connect_readonly(path=None):
    """Read-only connection for `lauds sql`: writes fail at the SQLite level.
    Built with `Path.as_uri()` (RFC 3986 percent-encoding), not an f-string -
    a `LAUDS_HOME` containing `?`, `#` or `%` would otherwise land in the
    URI unescaped and get misparsed as query string / fragment instead of
    path."""
    path = Path(path or paths.db_path())
    if not path.exists():
        raise FileNotFoundError(f"no database at {path} - run `lauds sync` first")
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _course_id(conn, course):
    code, term = _canonical_code(course.code), _canonical_term(course.term)
    if not term:
        # Unknown term: attach to an existing row for this code, if any.
        # ponytail: a code under several real terms (a retake) picks one
        # arbitrarily; fine until we store history.
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
    # A lecture and its lab shell canonicalise to one row: a known grade
    # survives an unknown one (COALESCE; both known -> last wins), and the
    # shorter title wins (the lab shell's is usually the lecture's + "(Lab)").
    conn.execute(
        "INSERT INTO courses (code, term, title, grade) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(code, term) DO UPDATE SET "
        "title=CASE WHEN length(excluded.title) < length(courses.title) THEN excluded.title ELSE courses.title END, "
        "grade=COALESCE(excluded.grade, grade)",
        (code, term, course.title, course.grade),
    )
    return conn.execute("SELECT id FROM courses WHERE code=? AND term=?", (code, term)).fetchone()[0]


def _utc(due):
    if due is None:
        return None
    if due.tzinfo is None:  # models.Item forbids this; tolerate foreign objects
        return due.isoformat()
    return due.astimezone(timezone.utc).isoformat()


def save(conn, courses=(), items=(), textbooks=(), meetings=()):
    """Upsert courses, then items/textbooks/meetings matched to them by
    canonical course code. Items whose course isn't in *this call* keep an
    existing course link (COALESCE) or stay unlinked - never dropped.
    Textbooks/meetings with no matching course this call are skipped."""
    ids = {_canonical_code(c.code): _course_id(conn, c) for c in courses}
    for i in items:
        conn.execute(
            "INSERT INTO items (course_id, category, kind, title, due, due_utc, url, source, done, "
            "course_raw, description, points, files, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, url) DO UPDATE SET course_id=COALESCE(excluded.course_id, course_id), "
            "category=excluded.category, kind=excluded.kind, title=excluded.title, due=excluded.due, "
            "due_utc=excluded.due_utc, done=excluded.done, course_raw=excluded.course_raw, "
            "description=excluded.description, points=excluded.points, files=excluded.files, extra=excluded.extra",
            (ids.get(_canonical_code(i.course)), i.category, i.kind, i.title,
             i.due.isoformat() if i.due else None, _utc(i.due), i.url, i.source,
             None if i.done is None else int(i.done), i.course,
             getattr(i, "description", None), getattr(i, "points", None),
             json.dumps(jsonable(getattr(i, "files", []))), json.dumps(jsonable(getattr(i, "extra", {})))),
        )
    for t in textbooks:
        cid = ids.get(_canonical_code(t.course))
        if cid is None:
            continue
        conn.execute(
            "INSERT INTO textbooks (course_id, title, isbn, required, price, url) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(course_id, isbn) DO UPDATE SET title=excluded.title, required=excluded.required, "
            "price=excluded.price, url=excluded.url",
            (cid, t.title, t.isbn, int(t.required), t.price, t.url),
        )
    for m in meetings:
        cid = ids.get(_canonical_code(m.course))
        if cid is None:
            continue
        conn.execute(
            "INSERT INTO meetings (course_id, kind, days, start_time, end_time, location, term_start, term_end, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(course_id, kind, days, start_time, term_start, source) DO UPDATE SET "
            "end_time=excluded.end_time, location=excluded.location, term_end=excluded.term_end",
            (cid, m.kind, ",".join(m.days), m.start_time.isoformat(), m.end_time.isoformat(),
             m.location, m.term_start.isoformat(), m.term_end.isoformat(), m.source),
        )
    conn.commit()


def save_bundle(conn, bundle: Bundle):
    save(conn, bundle.courses, bundle.items, bundle.textbooks, bundle.meetings)


_ITEM_COLS = ("items.category, items.kind, items.title, items.due, items.url, items.done, items.source, items.id")


def upcoming(conn, category=None):
    """Items with a due date, soonest first (by instant, not by text: two
    offsets on the same day still sort chronologically). LEFT JOIN: an item
    whose course didn't resolve still shows, as "(unknown course)"."""
    q = ("SELECT COALESCE(courses.code, '(unknown course)'), " + _ITEM_COLS +
         " FROM items LEFT JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NOT NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.due_utc, items.id")
    return conn.execute(q, (category,) if category else ()).fetchall()


def undated(conn, category=None):
    """Items with no due date, most recently saved first. Same row shape as
    upcoming(); `due` always NULL. Like main, only items with a course."""
    # ponytail: main's INNER JOIN kept - an undated item with no course is
    # hidden here (upcoming() shows its dated siblings). Switch to LEFT JOIN
    # if that turns out to hide things students need.
    q = ("SELECT courses.code, " + _ITEM_COLS +
         " FROM items JOIN courses ON courses.id = items.course_id "
         "WHERE items.due IS NULL" + (" AND items.category = ?" if category else "") +
         " ORDER BY items.id DESC")
    return conn.execute(q, (category,) if category else ()).fetchall()


def courses(conn):
    return conn.execute("SELECT code, term, title, grade FROM courses ORDER BY code").fetchall()


def by_course(conn, category=None):
    """upcoming(), grouped under each course code, each list soonest-first."""
    grouped = {}
    for row in upcoming(conn, category):
        grouped.setdefault(row[0], []).append(row)
    return grouped


def textbooks(conn, code=None):
    """Every textbook with its course code, required first, then by title.
    `code` is canonicalised, so "cpsc121" finds "CPSC 121"."""
    q = ("SELECT courses.code, textbooks.title, textbooks.isbn, textbooks.required, "
         "textbooks.price, textbooks.url FROM textbooks JOIN courses ON courses.id = textbooks.course_id"
         + (" WHERE courses.code = ?" if code else "") + " ORDER BY textbooks.required DESC, textbooks.title")
    return conn.execute(q, (_canonical_code(code),) if code else ()).fetchall()


def schedule(conn):
    """Every recurring class meeting, by course then start time."""
    return conn.execute(
        "SELECT courses.code, meetings.kind, meetings.days, meetings.start_time, meetings.end_time, "
        "meetings.location, meetings.term_start, meetings.term_end, meetings.source "
        "FROM meetings JOIN courses ON courses.id = meetings.course_id "
        "ORDER BY courses.code, meetings.start_time"
    ).fetchall()


def get_item(conn, item_id):
    """One item as a dict (every column, JSON fields decoded, `course` =
    canonical code or None), or None if there's no such id."""
    conn_rf = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT items.*, courses.code AS course, courses.title AS course_title "
            "FROM items LEFT JOIN courses ON courses.id = items.course_id WHERE items.id = ?", (item_id,)
        ).fetchone()
    finally:
        conn.row_factory = conn_rf
    if row is None:
        return None
    d = dict(row)
    for k, empty in (("files", []), ("extra", {})):
        d[k] = json.loads(d[k]) if d[k] else empty
    d["done"] = None if d["done"] is None else bool(d["done"])
    return d


# --- sync status -----------------------------------------------------------

def record_sync(conn, source, ok, counts=None, error=None, at=None):
    """Note one sync attempt. A failure keeps the previous success's time and counts."""
    at = (at or datetime.now(timezone.utc)).isoformat()
    conn.execute(
        "INSERT INTO sync_status (source, last_attempt, last_success, ok, counts, error) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt, ok=excluded.ok, error=excluded.error, "
        "last_success=COALESCE(excluded.last_success, last_success), counts=COALESCE(excluded.counts, counts)",
        (source, at, at if ok else None, int(bool(ok)), json.dumps(counts) if ok and counts is not None else None,
         None if ok else (error or "failed")),
    )
    conn.commit()


def sync_status(conn):
    """[(source, last_attempt, last_success, ok, counts_dict, error)], by source."""
    rows = conn.execute("SELECT source, last_attempt, last_success, ok, counts, error FROM sync_status ORDER BY source")
    return [(s, a, ls, bool(ok), json.loads(c) if c else None, e) for s, a, ls, ok, c, e in rows]
