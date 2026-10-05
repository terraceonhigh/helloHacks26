import functools
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

from icalendar import Calendar as ICalendar

from hub import db
from hub.api import ALLOWED_ORIGIN, Handler, _announcements, _upcoming
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
