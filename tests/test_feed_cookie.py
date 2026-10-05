"""/api/feed's httpOnly cookie, against BOTH implementations: hub/api.py
(local mode) and web/api/feed.py (the Vercel function). Network-free:
hub.ics.fetch_untrusted is monkeypatched, so nothing here reaches Canvas."""
import functools
import http.client
import importlib.util
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from hub import api, db, ics
from hub.models import Item

ROOT = Path(__file__).resolve().parents[1]
FEED_URL = "https://canvas.ubc.ca/feeds/calendars/user_SECRETtoken123.ics"
EXPECTED_COOKIE = (
    f"lauds_feed={quote(FEED_URL, safe='')}; HttpOnly; Secure; SameSite=Strict; "
    "Path=/api/feed; Max-Age=2592000"
)
ITEM = Item(course="CPSC 110", category="task", kind="assignment", title="PS4",
            due=datetime.now(timezone.utc) + timedelta(days=2),
            url="https://canvas.ubc.ca/courses/1/assignments/2", source="canvas")


def _vercel_handler():
    spec = importlib.util.spec_from_file_location("vercel_feed", ROOT / "web" / "api" / "feed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.handler


@pytest.fixture(params=["local", "vercel"])
def server(request, tmp_path, monkeypatch):
    """(port, origin that counts as same-origin, calls made to the fetcher)."""
    calls = []

    def fake_fetch(url, source):
        calls.append(url)
        if not ics.is_allowed_feed_host(url):
            raise ValueError("that isn't an allowed Canvas calendar-feed host")
        return [ITEM]

    monkeypatch.setattr(ics, "fetch_untrusted", fake_fetch)
    monkeypatch.setattr(db, "connect", functools.partial(db.connect, tmp_path / "hub.db"))
    handler = api.Handler if request.param == "local" else _vercel_handler()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    origin = api.ALLOWED_ORIGIN if request.param == "local" else f"http://127.0.0.1:{port}"
    yield port, origin, calls
    srv.shutdown()


def _call(port, method, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if data is not None else {}
    hdrs.update(headers or {})
    conn.request(method, "/api/feed", body=data, headers=hdrs)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, res.getheader("Set-Cookie"), raw.decode()


def test_post_success_sets_exactly_the_specified_cookie(server):
    port, origin, _ = server
    status, cookie, raw = _call(port, "POST", {"url": FEED_URL}, {"Origin": origin})
    assert status == 200
    assert cookie == EXPECTED_COOKIE
    assert json.loads(raw)[0]["title"] == "PS4"
    assert FEED_URL not in raw and "SECRETtoken123" not in raw


def test_post_to_a_disallowed_host_is_400_and_sets_no_cookie(server):
    port, origin, _ = server
    status, cookie, raw = _call(port, "POST", {"url": "https://evil.example.com/x.ics"}, {"Origin": origin})
    assert status == 400
    assert cookie is None
    assert "evil.example.com" not in raw


def test_post_failure_sets_no_cookie_and_hides_the_error(server, monkeypatch):
    port, origin, _ = server

    def boom(url, source):
        raise RuntimeError(f"exploded fetching {url}")

    monkeypatch.setattr(ics, "fetch_untrusted", boom)
    status, cookie, raw = _call(port, "POST", {"url": FEED_URL}, {"Origin": origin})
    assert status == 502
    assert cookie is None
    assert "SECRETtoken123" not in raw


def test_get_without_a_cookie_is_404(server):
    port, _, calls = server
    status, cookie, raw = _call(port, "GET")
    assert status == 404
    assert json.loads(raw) == {"error": "no feed connected"}
    assert cookie is None and calls == []


def test_get_reads_the_url_from_the_cookie(server):
    port, _, calls = server
    status, cookie, raw = _call(port, "GET", headers={"Cookie": f"other=1; lauds_feed={quote(FEED_URL, safe='')}"})
    assert status == 200
    assert calls == [FEED_URL]
    assert json.loads(raw)[0]["title"] == "PS4"
    assert "SECRETtoken123" not in raw
    assert cookie is None  # GET never re-issues the secret


def test_delete_clears_the_cookie(server):
    port, origin, _ = server
    status, cookie, raw = _call(port, "DELETE", headers={"Origin": origin})
    assert status == 204
    assert raw == ""
    assert cookie == "lauds_feed=; HttpOnly; Secure; SameSite=Strict; Path=/api/feed; Max-Age=0"


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_foreign_origin_is_rejected_on_state_changing_methods(server, method):
    port, _, calls = server
    body = {"url": FEED_URL} if method == "POST" else None
    status, cookie, _ = _call(port, method, body, {"Origin": "https://evil.example"})
    assert status == 403
    assert cookie is None and calls == []


def test_the_url_is_never_logged(server, capfd):
    port, origin, _ = server
    _call(port, "POST", {"url": FEED_URL}, {"Origin": origin})
    _call(port, "GET", headers={"Cookie": f"lauds_feed={quote(FEED_URL, safe='')}"})
    _call(port, "POST", {"url": "https://evil.example.com/SECRETtoken123.ics"}, {"Origin": origin})
    out, err = capfd.readouterr()
    assert "SECRETtoken123" not in out + err
    assert "/api/feed" not in out + err  # no request lines at all


def test_feed_url_from_cookie_ignores_other_cookies():
    assert ics.feed_url_from_cookie(None) is None
    assert ics.feed_url_from_cookie("lauds_feedx=1; a=b") is None
    assert ics.feed_url_from_cookie(f"a=b; lauds_feed={quote(FEED_URL, safe='')}") == FEED_URL
