import functools
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from icalendar import Calendar as ICalendar

from hub import brightspace, db, webwork
from hub.api import ALLOWED_ORIGIN, Handler, _announcements, _undated_tasks, _upcoming
from hub.models import Course, Item

NOW = datetime.now(timezone.utc)
COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")


def test_done_items_are_excluded_regardless_of_due_date():
    conn = db.connect(":memory:")
    done = Item(course="CPSC 121", category="task", kind="assignment", title="PS2",
                due=NOW - timedelta(days=1), url="https://x/1", source="canvas", done=True)
    db.save(conn, [COURSE], [done])
    assert _upcoming(conn) == []


def test_rows_carry_status_and_urgency():
    conn = db.connect(":memory:")
    overdue = Item(course="CPSC 121", category="task", kind="assignment", title="Final project",
                   due=NOW - timedelta(hours=1), url="https://x/2", source="canvas")
    db.save(conn, [COURSE], [overdue])
    rows = _upcoming(conn)
    assert len(rows) == 1
    assert rows[0]["status"] == "overdue"
    assert rows[0]["urgency"] in ("overdue", "critical", "high", "medium", "low")


def test_sorted_most_urgent_first():
    conn = db.connect(":memory:")
    quiet = Item(course="CPSC 121", category="material", kind="reading", title="Read ch. 4",
                 due=NOW + timedelta(hours=2), url="https://x/3", source="canvas")
    urgent = Item(course="CPSC 121", category="task", kind="exam", title="Final exam",
                  due=NOW + timedelta(hours=2), url="https://x/4", source="canvas")
    db.save(conn, [COURSE], [quiet, urgent])
    rows = _upcoming(conn)
    assert rows[0]["title"] == "Final exam"


def test_announcements_excludes_undated_items_that_are_not_announcements():
    # An undated Canvas assignment (hub/canvas.py's to_undated_item, #43) or
    # an unopened PrairieLearn assessment has no due date either, and used to
    # leak into this feed looking like an announcement.
    conn = db.connect(":memory:")
    announcement = Item(course="CPSC 121", category="task", kind="announcement", title="Welcome!",
                         due=None, url="https://x/a", source="canvas")
    undated_assignment = Item(course="CPSC 121", category="task", kind="assignment", title="Reading response",
                               due=None, url="https://x/b", source="canvas")
    db.save(conn, [COURSE], [announcement, undated_assignment])
    assert [r["title"] for r in _announcements(conn)] == ["Welcome!"]


def test_undated_tasks_is_the_complement_of_announcements():
    # Verified live: a real WeBWorK account connected successfully, but
    # every one of its 7 real problem sets came back due=None (its own
    # module docstring: a due date only exists for a currently-open set) -
    # before this endpoint existed, they were invisible everywhere.
    conn = db.connect(":memory:")
    announcement = Item(course="CPSC 121", category="task", kind="announcement", title="Welcome!",
                         due=None, url="https://x/a", source="canvas")
    undated_problemset = Item(course="CPSC 121", category="task", kind="problemset", title="BMEG230-Statics-A2",
                               due=None, url="https://x/b", source="webwork")
    db.save(conn, [COURSE], [announcement, undated_problemset])
    assert [r["title"] for r in _undated_tasks(conn)] == ["BMEG230-Statics-A2"]


def _running_server(tmp_path, monkeypatch):
    # These spin up the real server, which calls db.connect() with no args -
    # redirect that to a throwaway file so a CORS test never touches a real
    # ~/.ubc-hub/hub.db.
    monkeypatch.setattr(db, "connect", functools.partial(db.connect, tmp_path / "hub.db"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_cors_allows_the_web_dev_origin(tmp_path, monkeypatch):
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/courses", headers={"Origin": ALLOWED_ORIGIN})
        with urllib.request.urlopen(req) as res:
            assert res.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
    finally:
        server.shutdown()


def test_cors_rejects_other_origins(tmp_path, monkeypatch):
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/courses", headers={"Origin": "http://evil.example"})
        with urllib.request.urlopen(req) as res:
            assert res.headers.get("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown()


def test_options_preflight(tmp_path, monkeypatch):
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/connect/canvas", method="OPTIONS",
                                      headers={"Origin": ALLOWED_ORIGIN})
        with urllib.request.urlopen(req) as res:
            assert res.status == 204
            assert res.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
            assert "POST" in res.headers["Access-Control-Allow-Methods"]
    finally:
        server.shutdown()


def test_post_from_a_foreign_origin_is_rejected_before_doing_anything(tmp_path, monkeypatch):
    # DNS rebinding: a page on an attacker domain that resolves to 127.0.0.1
    # would otherwise be able to trigger a real /api/feed fetch or Canvas
    # login. The 403 must land before the endpoint runs, not just be hidden
    # from a browser reading the response via CORS.
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/feed", method="POST",
            data=b'{"url": "https://canvas.ubc.ca/feeds/calendars/x.ics"}',
            headers={"Origin": "http://evil.example", "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        server.shutdown()


def test_post_with_no_origin_header_is_allowed_through(tmp_path, monkeypatch):
    # A non-browser client (curl, a script) never sends an Origin header at
    # all - only a browser always does, so this must not be blocked as if it
    # were a forged one.
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/feed", method="POST",
            data=b'{"url": "https://evil.example.com/feed.ics"}',
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            # Rejected by the feed host allowlist, not by the origin check.
            assert e.code == 400
    finally:
        server.shutdown()


def _seed_calendar_items(tmp_path):
    # Uses the real, unpatched db.connect (this runs before _running_server
    # does its own monkeypatch below) - patching db.connect here too would
    # double-wrap functools.partial and break the *next* patch's call signature.
    conn = db.connect(tmp_path / "hub.db")
    quiz = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
                due=NOW + timedelta(days=2), url="https://x/q2", source="canvas")
    exam = Item(course="CPSC 121", category="deadline", kind="exam", title="Midterm 1",
                due=NOW + timedelta(days=9), url="https://x/e1", source="canvas")
    db.save(conn, [COURSE], [quiz, exam])


def test_calendar_ics_serves_a_valid_combined_feed(tmp_path, monkeypatch):
    _seed_calendar_items(tmp_path)
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/calendar.ics") as res:
            assert res.status == 200
            assert res.headers["Content-Type"].startswith("text/calendar")
            cal = ICalendar.from_ical(res.read())
            summaries = sorted(str(ev["summary"]) for ev in cal.walk("VEVENT"))
            assert summaries == ["Midterm 1 [CPSC 121]", "Quiz 2 [CPSC 121]"]
    finally:
        server.shutdown()


def test_calendar_kind_ics_serves_only_that_kind(tmp_path, monkeypatch):
    _seed_calendar_items(tmp_path)
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/calendar/quiz.ics") as res:
            cal = ICalendar.from_ical(res.read())
            summaries = [str(ev["summary"]) for ev in cal.walk("VEVENT")]
            assert summaries == ["Quiz 2 [CPSC 121]"]
    finally:
        server.shutdown()


def test_api_calendar_kinds_lists_kinds_with_colors(tmp_path, monkeypatch):
    _seed_calendar_items(tmp_path)
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/calendar/kinds",
                                      headers={"Origin": ALLOWED_ORIGIN})
        with urllib.request.urlopen(req) as res:
            assert res.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
            kinds = json.loads(res.read())
            assert {"kind": "quiz", "color": "#7C3AED"} in kinds
            assert {"kind": "exam", "color": "#DC2626"} in kinds
    finally:
        server.shutdown()


def test_malformed_json_body_returns_400_not_a_crash(tmp_path, monkeypatch):
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/feed", method="POST",
            data=b"not json", headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        server.shutdown()


def test_non_object_json_body_returns_400_not_a_crash(tmp_path, monkeypatch):
    # A JSON array or string is valid JSON but has no .get("url") - .get()
    # on a list crashes the handler instead of a clean 400.
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/feed", method="POST",
            data=b'["not", "an", "object"]', headers={"Origin": ALLOWED_ORIGIN, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        server.shutdown()


def _post_json(port, path, payload, origin=ALLOWED_ORIGIN):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        data=json.dumps(payload).encode(), headers={"Origin": origin, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_connect_brightspace_rejects_a_non_https_base_without_ever_fetching(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(brightspace, "fetch", lambda *a, **k: called.append(1))
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/brightspace", {"base": "http://ubc.brightspace.com"})
        assert status == 400
        assert called == []
    finally:
        server.shutdown()


def test_connect_brightspace_saves_courses_from_a_valid_base(tmp_path, monkeypatch):
    fake_course = Course(code="MATH_V 100A ALL SECTIONS 2026W1", section="", term="", title="Calculus")
    monkeypatch.setattr(brightspace, "fetch", lambda base: ([fake_course], []))
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/brightspace", {"base": "https://ubc.brightspace.com"})
        assert status == 200
        assert body == {"ok": True, "courses": 1, "items": 0}
    finally:
        server.shutdown()


def test_connect_webwork_rejects_a_non_https_base_without_ever_fetching(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(webwork, "fetch", lambda *a, **k: called.append(1))
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/webwork", {"base": "http://webwork.example.edu", "course_code": "MATH 100"})
        assert status == 400
        assert called == []
    finally:
        server.shutdown()


def test_connect_webwork_requires_a_course_code(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(webwork, "fetch", lambda *a, **k: called.append(1))
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/webwork", {"base": "https://webwork.example.edu"})
        assert status == 400
        assert called == []
    finally:
        server.shutdown()


def test_connect_webwork_builds_the_course_itself_from_course_code(tmp_path, monkeypatch):
    # hub/webwork.py's fetch() returns items only - no catalogue join key on
    # its own page - so the Course record has to come from the caller.
    fake_item = Item(course="MATH 100", category="deadline", kind="quiz", title="WW1",
                      due=None, url="https://webwork.example.edu/1", source="webwork")
    monkeypatch.setattr(webwork, "fetch", lambda base, course_code: [fake_item])
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/webwork", {"base": "https://webwork.example.edu", "course_code": "MATH 100"})
        assert status == 200
        assert body == {"ok": True, "courses": 1, "items": 1}
    finally:
        server.shutdown()


def test_connect_webwork_joins_an_existing_course_instead_of_making_a_new_one(tmp_path, monkeypatch):
    # Real bug found live: a pre-existing Canvas course row stored as
    # "BMEG_V 230 101 2026W1" (predates canonical course codes) didn't join
    # with a fresh "BMEG 230" WeBWorK course, even though both name the
    # same real course - two separate cards, WeBWorK's items invisible on
    # the real one. _connect_webwork should find and reuse the existing
    # course's own stored identity instead of making a new "BMEG 230" row.
    db_path = tmp_path / "hub.db"
    conn = db.connect(db_path)
    conn.execute("INSERT INTO courses (code, term, title) VALUES ('BMEG_V 230 101 2026W1', '2026W1_V', 'Biomechanics I')")
    conn.commit()
    fake_item = Item(course="BMEG 230", category="task", kind="problemset", title="WW1",
                      due=None, url="https://webwork.elearning.ubc.ca/1", source="webwork")
    monkeypatch.setattr(webwork, "fetch", lambda base, course_code: [fake_item])
    server = _running_server(tmp_path, monkeypatch)
    try:
        port = server.server_address[1]
        status, body = _post_json(port, "/api/connect/webwork", {"base": "https://webwork.elearning.ubc.ca", "course_code": "BMEG 230"})
        assert status == 200
        assert body == {"ok": True, "courses": 1, "items": 1}
        rows = conn.execute("SELECT code FROM courses").fetchall()
        assert rows == [("BMEG_V 230 101 2026W1",)]  # one course, not two
        item_course = conn.execute(
            "SELECT courses.code FROM items JOIN courses ON courses.id = items.course_id WHERE items.source='webwork'"
        ).fetchone()
        assert item_course == ("BMEG_V 230 101 2026W1",)
    finally:
        server.shutdown()
