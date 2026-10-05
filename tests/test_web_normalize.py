import importlib.util
import io
import json
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "web" / "api" / "normalize.py"
spec = importlib.util.spec_from_file_location("web_normalize", MODULE)
normalize = importlib.util.module_from_spec(spec)
spec.loader.exec_module(normalize)


def call(body, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()

    class Request:
        headers = {"Content-Type": content_type, "Content-Length": str(len(data))}
        rfile = io.BytesIO(data)

        def _json(self, payload, status=200):
            self.status = status
            self.payload = payload

    req = Request()
    normalize.handler.do_POST(req)
    return req.status, req.payload


def test_stateless_route_maps_through_existing_canvas_adapter():
    status, payload = call({
        "source": "canvas",
        "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [{"course_id": 7, "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z",
                     "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3"}],
        "undated": [],
    })
    assert status == 200
    assert payload["stored"] is False
    assert payload["courses"][0]["code"] == "CPSC 121"
    assert payload["items"][0]["source"] == "canvas"


def test_stateless_route_bounds_and_rejects_bad_captures():
    assert call(b"{broken")[0] == 400
    assert call({"source": "../site"})[0] == 400
    assert call({"source": "canvas"}, content_type="text/plain")[0] == 400
    assert call(b"x" * (normalize.MAX_BODY + 1))[0] == 413
