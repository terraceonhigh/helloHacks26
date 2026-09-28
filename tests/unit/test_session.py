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


def test_fetch_with_session_relogs_once_on_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    (tmp_path / "s-state.json").write_text("{}")
    logins = []
    monkeypatch.setattr(session, "login", lambda site, base, **kw: logins.append(site))

    class Ctx:
        request = "REQ"

    class Browser:
        def new_context(self, storage_state):
            return Ctx()

        def close(self):
            pass

    class PW:
        chromium = type("C", (), {"launch": staticmethod(lambda **kw: Browser())})

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    calls = []

    def run(req):
        calls.append(req)
        if len(calls) == 1:
            raise NotLoggedIn
        return "ok"

    assert session.fetch_with_session("s", "https://b", run, _playwright=PW) == "ok"
    assert logins == ["s"] and calls == ["REQ", "REQ"]
