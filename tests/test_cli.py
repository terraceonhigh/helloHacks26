import requests

from hub import cli


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_main_gets_pretty_printed_json_from_the_selected_endpoint(monkeypatch, capsys):
    calls = []

    def fake_request(method, url, timeout=None):
        calls.append((method, url, timeout))
        return Response({"items": ["one"]})

    monkeypatch.setattr(cli.requests, "request", fake_request)

    assert cli.main(["upcoming", "--base-url", "http://hub.test/"]) == 0
    assert calls == [("GET", "http://hub.test/api/upcoming", cli.TIMEOUT_SECONDS)]
    assert capsys.readouterr().out == '{\n  "items": [\n    "one"\n  ]\n}\n'


def test_base_url_uses_the_environment_when_no_flag_is_given(monkeypatch):
    monkeypatch.setenv(cli.BASE_URL_ENV, "http://from-env.test")
    calls = []

    def fake_request(method, url, timeout=None):
        calls.append((method, url))
        return Response([])

    monkeypatch.setattr(cli.requests, "request", fake_request)

    assert cli.main(["courses"]) == 0
    assert calls == [("GET", "http://from-env.test/api/courses")]


def test_connect_command_posts_without_opening_a_real_browser(monkeypatch):
    calls = []

    def fake_request(method, url, timeout=None):
        calls.append((method, url))
        return Response({"ok": True})

    monkeypatch.setattr(cli.requests, "request", fake_request)

    assert cli.main(["connect-canvas"]) == 0
    assert calls == [("POST", "http://127.0.0.1:8000/api/connect/canvas")]


def test_connection_errors_are_one_line_and_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.requests,
        "request",
        lambda method, url, timeout=None: (_ for _ in ()).throw(requests.ConnectionError("refused")),
    )

    assert cli.main(["announcements"]) == 1
    assert capsys.readouterr().err == "error: GET http://127.0.0.1:8000/api/announcements: refused\n"


def test_http_errors_are_one_line_and_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli.requests, "request", lambda method, url, timeout=None: Response({}, status_code=503))

    assert cli.main(["courses"]) == 1
    assert capsys.readouterr().err == "error: GET http://127.0.0.1:8000/api/courses: HTTP 503\n"


def test_invalid_json_is_one_line_and_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli.requests, "request", lambda method, url, timeout=None: Response(ValueError()))

    assert cli.main(["courses"]) == 1
    assert capsys.readouterr().err == "error: GET http://127.0.0.1:8000/api/courses: response was not valid JSON\n"
