"""Parity-to-superset for lauds.adapters.canvas against every golden under
tests/oracle/canvas/*.json (offline and live_).

Each golden's `inputs` is one or more raw JSON fixtures; which parse
function(s) to replay them through, and with what extra params, is fixed
per case name (mirroring how tools/harvest_oracle.py drove main's own
functions for that same golden).
"""
import json

import pytest

from lauds.adapters import canvas
from lauds.models import Bundle
from tests.parity.superset import golden_paths, load_inputs, assert_superset

GOLDENS = golden_paths("canvas")


def _bundle_for(golden: dict) -> Bundle:
    case = golden["case"]
    inputs = load_inputs(golden)

    if case == "planner_items_mapping":
        raw = {k: json.loads(v) for k, v in inputs.items()}["canvas/planner_items.json"]
        courses = [canvas.to_course(raw["course"])]
        codes = {raw["course"]["id"]: raw["course"]["course_code"]}
        items = [canvas.to_item(raw[k], codes) for k in ("quiz", "event", "discussion_default", "announcement")]
        return Bundle(courses=courses, items=items)

    if case == "undated_assignment":
        (raw,) = (json.loads(v) for v in inputs.values())
        return Bundle(items=[canvas.to_undated_item(raw, "CPSC 121")])

    if case == "done_from_submissions":
        (rows,) = (json.loads(v) for v in inputs.values())
        codes = {7: "CPSC 121"}
        return Bundle(items=[canvas.to_item(p, codes) for p in rows])

    if case == "extension_capture":
        (capture,) = (json.loads(v) for v in inputs.values())
        return canvas.parse_capture(capture)

    if case in ("extension_js_capture_minimal", "extension_js_capture_completed"):
        (capture,) = (json.loads(v) for v in inputs.values())
        return canvas.parse_capture(capture)

    if case == "selfhost":
        return _run_live_golden(golden, inputs)

    raise AssertionError(f"tests/parity/test_canvas.py doesn't know case {case!r}; add a branch for it")


def _run_live_golden(golden, inputs):
    """live_selfhost: replay the recorded raw HTTP bodies through canvas._run
    exactly as canvas.fetch() would have called them, in the golden's own
    `inputs` order (courses, planner/items, then one assignments page per
    course in `raw["courses"]`'s order)."""
    from datetime import date

    bodies = list(inputs.values())  # courses, planner/items, then assignments pages in course order
    courses_body, planner_body, *assignment_bodies = bodies

    class _FakeReq:
        def __init__(self, pages):
            self._pages = list(pages)

        def get(self, url):
            return _FakeResp(self._pages.pop(0))

    class _FakeResp:
        def __init__(self, body):
            self._body = body
            self.status, self.ok, self.headers = 200, True, {}

        def text(self):
            return self._body

    req = _FakeReq([courses_body, planner_body, *assignment_bodies])
    extra = golden.get("extra", {})
    start = date.fromisoformat(extra["start"])
    end = date.fromisoformat(extra["end"])
    # The self-hosted oracle isn't canvas.ubc.ca - monkeypatch BASE for the
    # call, same as tools/harvest_live.py did to harvest this golden in the
    # first place (never a product-code change, just how a self-host target
    # is selected for one run).
    saved_base = canvas.BASE
    canvas.BASE = extra["base"]
    try:
        return canvas._run(req, start, end)
    finally:
        canvas.BASE = saved_base


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_canvas_parity(path):
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert_superset(golden, _bundle_for(golden))
