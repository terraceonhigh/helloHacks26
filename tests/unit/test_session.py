import pytest

from lauds import session
from lauds.session import NotLoggedIn, get, get_all, next_link


def test_next_link():
    h = '<https://x/api/courses?page=2>; rel="next", <https://x/api/courses?page=1>; rel="first"'
    assert next_link(h) == "https://x/api/courses?page=2"
    assert next_link('<x>; rel="last"') is None
    assert next_link(None) is None


class FakeResponse:
    def __init__(self, status, body="[]", link=None):
        self.status, self.ok = status, status < 400
        self.headers = {"link": link} if link else {}
        self._body = body

    def text(self):
        return self._body


class FakeRequestContext:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url):
        self.calls.append(url)
        return self.responses.pop(0)


def test_get_all_follows_pagination():
    req = FakeRequestContext([FakeResponse(200, "[1, 2]", link='<https://x/y?page=2>; rel="next"'),
                              FakeResponse(200, "[3]")])
    assert get_all(req, "https://x/y", {"per_page": 100}) == [1, 2, 3]
    assert req.calls == ["https://x/y?per_page=100", "https://x/y?page=2"]


def test_get_all_raises_on_expired_session():
    with pytest.raises(NotLoggedIn):
        get_all(FakeRequestContext([FakeResponse(401)]), "https://x/y", {})


def test_429_backs_off_then_succeeds():
    slept = []
    req = FakeRequestContext([FakeResponse(429), FakeResponse(429), FakeResponse(200, "[7]")])
    assert get_all(req, "https://x/y", sleep=slept.append) == [7]
    assert slept == [1, 2]


def test_other_errors_raise():
    with pytest.raises(RuntimeError, match="500"):
        get(FakeRequestContext([FakeResponse(500)]), "https://x/y", sleep=lambda s: None)


def test_unwrap_strips_guard():
    req = FakeRequestContext([FakeResponse(200, "while(1);[1]")])
    import json
    assert get_all(req, "u", unwrap=lambda t: json.loads(t.removeprefix("while(1);"))) == [1]


def test_self_linking_pagination_cannot_hang():
    class Loop:
        def get(self, url):
            return FakeResponse(200, "[1]", link='<u>; rel="next"')
    with pytest.raises(RuntimeError, match="pagination"):
        get_all(Loop(), "u", max_pages=5)


def test_state_path_under_lauds_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    assert session.state_path("canvas") == tmp_path / "canvas-state.json"


class _FakeCtx:
    request = "REQ"


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def new_context(self, storage_state):
        return _FakeCtx()

    def close(self):
        self.closed = True


class _FakePW:
    def __init__(self):
        self.browsers = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        outer = self

        class C:
            @staticmethod
            def launch(**kw):
                b = _FakeBrowser()
                outer.browsers.append(b)
                return b
        return C


def test_fetch_with_session_raises_not_logged_in_with_no_saved_session_and_never_opens_a_browser(
        tmp_path, monkeypatch):
    """BRIEF major finding: no saved session must never mean "open an
    interactive browser and block `sync` on it" - it must come back as
    NotLoggedIn (stale), same as an expired one, so only `lauds login
    <source>` drives an interactive login."""
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))

    def boom(*a, **kw):
        raise AssertionError("fetch_with_session must never call session.login() itself")

    monkeypatch.setattr(session, "login", boom)
    pw = _FakePW()
    with pytest.raises(NotLoggedIn):
        session.fetch_with_session("s", "https://b", lambda req: "unreachable", _playwright=pw)
    assert pw.browsers == []  # never even launched a browser


def test_fetch_with_session_lets_an_expired_session_propagate_without_relogging(tmp_path, monkeypatch):
    """BRIEF blocker finding: re-logging in from inside fetch_with_session's
    own `with _playwright()` block nests two sync_playwright() calls and
    crashes for real (live-verified in the lauds venv). NotLoggedIn must
    propagate untouched instead, and login() must never be called while a
    Playwright context is open - the caller (`lauds.sync`) is what turns
    this into "stale, re-login needed"."""
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    (tmp_path / "s-state.json").write_text("{}")
    monkeypatch.setattr(session, "login", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("fetch_with_session must never call session.login() itself")))

    pw = _FakePW()
    with pytest.raises(NotLoggedIn):
        session.fetch_with_session("s", "https://b", lambda req: (_ for _ in ()).throw(NotLoggedIn), _playwright=pw)
    assert len(pw.browsers) == 1 and pw.browsers[0].closed  # opened once, closed on the way out


def test_fetch_with_session_runs_against_the_saved_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    (tmp_path / "s-state.json").write_text("{}")
    pw = _FakePW()
    calls = []

    def run(req):
        calls.append(req)
        return "ok"

    assert session.fetch_with_session("s", "https://b", run, _playwright=pw) == "ok"
    assert calls == ["REQ"]
    assert len(pw.browsers) == 1 and pw.browsers[0].closed
