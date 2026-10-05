"""Hosted store: key auth, body validation, hub.db's Hosted backend, and the
web/api sync/items/session routes. Network-free: the Postgres SQL runs
against in-memory SQLite (db.Hosted(conn, student, "?")), and the routes are
driven with in-memory request/response streams, not a socket."""
import copy
import email
import importlib.util
import io
import json
import secrets
import sqlite3
from pathlib import Path

import pytest

from hub import db, hosted

API = Path(__file__).resolve().parents[1] / "web" / "api"
KEY_A = secrets.token_urlsafe(32)
KEY_B = secrets.token_urlsafe(32)

BODY = {
    "source": "canvas",
    "stored": False,
    "courses": [{"code": "CPSC 121 101 2026W1", "section": "101", "term": "2026 Winter Term 1",
                 "title": "Models of Computation", "grade": 84.5}],
    "items": [{"course": "CPSC 121", "category": "deadline", "kind": "quiz", "title": "Quiz 2",
               "due": "2026-09-30T06:59:00+00:00", "url": "https://canvas.example/q/1",
               "source": "canvas", "done": None, "files": []}],
}


def body(**changes):
    b = copy.deepcopy(BODY)
    item = changes.pop("item", None)
    if item:
        b["items"][0].update(item)
    b.update(changes)
    return b


def store(conn, key):
    return db.init_hosted(db.Hosted(conn, hosted.student_id(key), "?"))


# --- keys ---------------------------------------------------------------------

def test_key_format():
    assert hosted.valid_key(KEY_A) and len(KEY_A) == 43
    for bad in [None, "", "short", KEY_A[:42], KEY_A + "!", KEY_A[:40] + "a b", 12345]:
        assert not hosted.valid_key(bad)


def test_student_id_is_sha256_and_raw_key_is_never_stored():
    conn = sqlite3.connect(":memory:")
    s = store(conn, KEY_A)
    assert s.student == hosted.student_id(KEY_A) != KEY_A and len(s.student) == 64
    db.save(s, *hosted.parse_sync(BODY))
    dump = "\n".join(conn.iterdump())
    assert s.student in dump and KEY_A not in dump


# --- validation ---------------------------------------------------------------

def test_parse_sync_accepts_normalized_body():
    courses, items = hosted.parse_sync(BODY)
    assert courses[0].code == "CPSC 121 101 2026W1"
    assert items[0].due.tzinfo is not None and items[0].source == "canvas"
    assert hosted.parse_sync(body(item={"due": None}))[1][0].due is None
    assert hosted.parse_sync({"source": "prairielearn", "courses": [], "items": []}) == ([], [])


@pytest.mark.parametrize("bad", [
    [],
    body(source="Canvas!"),
    body(source=""),
    body(source=None),
    body(items="nope"),
    body(items=BODY["items"] * (hosted.MAX_ROWS + 1)),
    body(courses=BODY["courses"] * (hosted.MAX_ROWS + 1)),
    body(item={"due": "2026-09-30T06:59:00"}),  # naive
    body(item={"due": "next tuesday"}),
    body(item={"url": "http://canvas.example/q/1"}),
    body(item={"url": "javascript:alert(1)"}),
    body(item={"source": "workday"}),  # item disagrees with the body's source
    body(item={"category": "urgent"}),
    body(item={"title": ""}),
    body(item={"done": "yes"}),
    body(item={"evil": 1}),  # not a field of hub.models.Item
    body(courses=[{"code": "CPSC 121"}]),  # missing title
    body(courses=[{**BODY["courses"][0], "grade": "A+"}]),
    body(items=[{k: v for k, v in BODY["items"][0].items() if k != "title"}]),
])
def test_parse_sync_rejects(bad):
    with pytest.raises(ValueError):
        hosted.parse_sync(bad)


# --- hub.db Hosted backend ------------------------------------------------------

def test_hosted_save_upcoming_and_courses():
    s = store(sqlite3.connect(":memory:"), KEY_A)
    db.save(s, *hosted.parse_sync(BODY))
    assert db.upcoming(s) == [("CPSC 121", "deadline", "quiz", "Quiz 2", "2026-09-30T06:59:00+00:00",
                               "https://canvas.example/q/1", None, "canvas")]
    assert db.courses(s) == [("CPSC 121", "2026W1", "Models of Computation", 84.5)]
    assert list(db.by_course(s)) == ["CPSC 121"]


def test_hosted_due_is_stored_in_utc_so_it_sorts():
    s = store(sqlite3.connect(":memory:"), KEY_A)
    later = body(item={"due": "2026-09-30T01:00:00-07:00", "url": "https://canvas.example/q/2", "title": "Later"})
    db.save(s, *hosted.parse_sync(later))  # 08:00 UTC - after Quiz 2's 06:59 UTC
    db.save(s, *hosted.parse_sync(BODY))
    assert [r[3] for r in db.upcoming(s)] == ["Quiz 2", "Later"]


def test_hosted_upsert_is_idempotent():
    s = store(sqlite3.connect(":memory:"), KEY_A)
    db.save(s, *hosted.parse_sync(BODY))
    db.save(s, *hosted.parse_sync(BODY))
    db.save(s, *hosted.parse_sync(body(item={"title": "Quiz 2 (moved)"})))
    assert [r[3] for r in db.upcoming(s)] == ["Quiz 2 (moved)"]
    assert len(db.courses(s)) == 1
    db.init_hosted(s)  # schema creation is idempotent too


def test_hosted_resync_replaces_stale_done_value():
    s = store(sqlite3.connect(":memory:"), KEY_A)
    db.save(s, *hosted.parse_sync(body(item={"done": False})))
    db.save(s, *hosted.parse_sync(body(item={"done": True})))
    assert db.upcoming(s)[0][6] == 1
    db.save(s, *hosted.parse_sync(body(item={"done": False})))
    assert db.upcoming(s)[0][6] == 0


def test_students_are_isolated_and_wipe_is_scoped():
    conn = sqlite3.connect(":memory:")
    a, b = store(conn, KEY_A), store(conn, KEY_B)
    db.save(a, *hosted.parse_sync(BODY))
    db.save(b, *hosted.parse_sync(body(item={"title": "B's quiz"})))  # same (source, url), other student
    assert [r[3] for r in db.upcoming(a)] == ["Quiz 2"]
    assert [r[3] for r in db.upcoming(b)] == ["B's quiz"]
    db.wipe(a)
    assert db.upcoming(a) == [] and db.courses(a) == []
    assert [r[3] for r in db.upcoming(b)] == ["B's quiz"] and len(db.courses(b)) == 1


def test_local_sqlite_path_is_untouched():
    conn = db.connect(":memory:")
    db.save(conn, *hosted.parse_sync(BODY))
    assert db.upcoming(conn)[0][3] == "Quiz 2"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'hosted_%'").fetchall() == []


# --- routes -----------------------------------------------------------------------

def route(name):
    spec = importlib.util.spec_from_file_location(f"api_{name}", API / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.handler


def call(name, method, payload=None, headers=None):
    """Drive a route's handler without a socket; returns (status, headers, json)."""
    raw = json.dumps(payload).encode() if payload is not None else b""
    h = {"Content-Type": "application/json", "Content-Length": str(len(raw)), **(headers or {})}
    req = route(name).__new__(route(name))
    req.rfile, req.wfile = io.BytesIO(raw), io.BytesIO()
    req.headers = email.message_from_string("".join(f"{k}: {v}\n" for k, v in h.items()))
    req.command, req.path, req.request_version = method, f"/api/{name}", "HTTP/1.1"
    req.requestline, req.client_address = f"{method} /api/{name} HTTP/1.1", ("0.0.0.0", 0)
    getattr(req, f"do_{method}")()
    head, _, out = req.wfile.getvalue().partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    resp_headers = email.message_from_string("\n".join(lines[1:]))
    return int(lines[0].split()[1]), resp_headers, json.loads(out)


@pytest.fixture
def pg(monkeypatch):
    """DATABASE_URL set, but connect_hosted() hands back one shared in-memory
    SQLite (whose close() is a no-op) instead of dialing Postgres."""
    conn = sqlite3.connect(":memory:")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake.invalid/db")

    class Kept(db.Hosted):
        def close(self):
            pass

    monkeypatch.setattr(db, "connect_hosted", lambda student, url=None: db.init_hosted(Kept(conn, student, "?")))
    return conn


@pytest.mark.parametrize("name,method", [("sync", "POST"), ("sync", "DELETE"), ("items", "GET"), ("session", "POST")])
def test_routes_503_until_database_url_is_set(monkeypatch, name, method):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    status, _, out = call(name, method, BODY, {"Authorization": f"Bearer {KEY_A}"})
    assert (status, out) == (503, {"error": "hosted storage not configured"})


def test_sync_then_items_round_trip_and_isolation(pg):
    auth_a = {"Authorization": f"Bearer {KEY_A}"}
    status, headers, out = call("sync", "POST", BODY, auth_a)
    assert (status, out) == (200, {"stored": True, "items": 1})
    assert headers["Cache-Control"] == "no-store"
    status, _, out = call("items", "GET", headers={"Cookie": f"{hosted.COOKIE}={KEY_A}"})
    assert status == 200 and [i["title"] for i in out["items"]] == ["Quiz 2"]
    assert out["items"][0]["status"] and out["items"][0]["urgency"]
    assert out["courses"] == [{"code": "CPSC 121", "term": "2026W1", "title": "Models of Computation", "grade": 84.5}]
    _, _, out_b = call("items", "GET", headers={"Authorization": f"Bearer {KEY_B}"})
    assert out_b == {"items": [], "courses": []}  # B can't see A
    call("sync", "POST", body(item={"title": "B's"}), {"Authorization": f"Bearer {KEY_B}"})
    assert call("sync", "DELETE", headers=auth_a)[2] == {"deleted": True}
    assert call("items", "GET", headers=auth_a)[2]["items"] == []
    assert [i["title"] for i in call("items", "GET", headers={"Authorization": f"Bearer {KEY_B}"})[2]["items"]] == ["B's"]
    assert KEY_A not in "\n".join(pg.iterdump())


@pytest.mark.parametrize("headers,payload,expected", [
    ({}, BODY, 401),
    ({"Authorization": "Bearer short"}, BODY, 401),
    ({"Authorization": f"Bearer {KEY_A}", "Origin": "https://evil.example"}, BODY, 403),
    ({"Authorization": f"Bearer {KEY_A}", "Content-Type": "text/plain"}, BODY, 415),
    ({"Authorization": f"Bearer {KEY_A}"}, body(item={"url": "http://x/1"}), 400),
    ({"Authorization": f"Bearer {KEY_A}", "Origin": "chrome-extension://abcdef"}, BODY, 200),
    ({"Authorization": f"Bearer {KEY_A}", "Origin": hosted.ALLOWED_ORIGIN}, BODY, 200),
])
def test_sync_rejects_bad_requests(pg, headers, payload, expected):
    status, _, out = call("sync", "POST", payload, headers)
    assert status == expected
    assert KEY_A not in json.dumps(out)  # never echoed


def test_sync_rejects_oversized_body(pg):
    status, _, _ = call("sync", "POST", BODY, {"Authorization": f"Bearer {KEY_A}",
                                              "Content-Length": str(hosted.MAX_BODY + 1)})
    assert status == 413


def test_session_sets_strict_httponly_cookie(pg):
    status, headers, out = call("session", "POST", {"key": KEY_A})
    assert (status, out) == (200, {"ok": True})
    cookie = headers["Set-Cookie"]
    assert cookie.startswith(f"{hosted.COOKIE}={KEY_A};")
    for flag in ["HttpOnly", "Secure", "SameSite=Strict", "Path=/api", "Max-Age=2592000"]:
        assert flag in cookie.split("; ")
    assert KEY_A not in json.dumps(out)


def test_session_rejects_bad_key_and_origin(pg):
    assert call("session", "POST", {"key": "nope"})[0] == 400
    status, headers, _ = call("session", "POST", {"key": KEY_A}, {"Origin": "https://evil.example"})
    assert status == 403 and "Set-Cookie" not in headers


def test_no_request_logging_even_under_vercels_wrapper(capsys):
    from http.server import BaseHTTPRequestHandler

    class Loud(BaseHTTPRequestHandler):  # vercel_runtime's BaseHandler re-implements log_message to print
        def log_message(self, fmt, *args):
            print("LOGGED", fmt % args)

    wrapped = type("Handler", (Loud, route("sync")), {})
    req = wrapped.__new__(wrapped)
    req.requestline, req.client_address = "POST /api/sync HTTP/1.1", ("0.0.0.0", 0)
    req.log_request(200)
    req.log_error("boom")
    assert "LOGGED" not in capsys.readouterr().out
