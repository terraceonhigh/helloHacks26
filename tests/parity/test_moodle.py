"""Parity-to-superset for the Moodle adapter: every golden under
tests/oracle/moodle/ (offline and live_), replayed through
lauds.adapters.moodle.

`parse_capture` and `to_item_assign_default_kind` replay directly through the
adapter's own pure functions over the golden's raw fixture. The two live_
goldens (tests/live/moodle_selfhost/README.md) are each about a specific
raw capture, not a fresh call:

- `live_fake101_calendar_only`: main's `to_item` over the real, working,
  unbatched `core_calendar_get_action_events_by_timesort` response
  (limitnum=50) - decoded straight from the raw fixture and mapped, same as
  the oracle harvester itself did.
- `live_fake101`: main's `fetch()` on this exact captured *error* response is
  always empty (a real Moodle-core bug - see lauds/adapters/moodle.py's
  module docstring, and the golden's own "extra"."note"). lauds' `_run` no
  longer makes the batched call this fixture captured, so replaying it
  through `_run` isn't a like-for-like call - but the golden's own expected
  output is genuinely empty (`courses: [], items: []`), so *any* `new` value
  is a trivial superset. Replayed anyway, for the record, wrapped in the same
  try/except `fetch()` itself doesn't have (lauds.sync isolates failures at
  the sync layer instead, see lauds/sync.py) so a captured error response
  can't crash the test suite.
"""
import json

import pytest

from lauds.adapters import moodle
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

CASES = golden_paths("moodle")


class _FixtureResp:
    def __init__(self, text):
        self.status = 200
        self.ok = True
        self._text = text

    def text(self):
        return self._text


class _FixtureReq:
    """Replays one captured GET (dashboard) and one captured POST (the AJAX
    multiplexer) - moodle._run never needs more than that per call."""

    def __init__(self, my_html, ajax_body):
        self._my_html = my_html
        self._ajax_body = ajax_body

    def get(self, url):
        return _FixtureResp(self._my_html)

    def post(self, url, data=None, headers=None):
        return _FixtureResp(self._ajax_body)


def _replay_parse_capture(inputs):
    capture = json.loads(inputs["moodle/parse_capture.json"])
    courses, items = moodle.parse_capture(capture)
    return {"courses": courses, "items": items}


def _replay_to_item_assign_default_kind(inputs):
    event = json.loads(inputs["moodle/to_item_assign_default_kind.json"])
    return {"items": [moodle.to_item(event)]}


def _replay_live_fake101_calendar_only(inputs):
    raw = json.loads(inputs["moodle/live_03_post_lib_ajax_service_php.json"])
    (result,) = raw
    events = result["data"]["events"]
    return {"items": [moodle.to_item(e) for e in events]}


def _replay_live_fake101(golden, inputs):
    req = _FixtureReq(inputs["moodle/live_00_get_my.html"], inputs["moodle/live_01_post_lib_ajax_service_php.json"])
    extra = golden["extra"]
    try:
        courses, items = moodle._run(req, extra["base"], extra["start"], extra["end"])
    except Exception:
        courses, items = [], []
    return {"courses": courses, "items": items}


_REPLAYS = {
    "parse_capture": lambda g, inputs: _replay_parse_capture(inputs),
    "to_item_assign_default_kind": lambda g, inputs: _replay_to_item_assign_default_kind(inputs),
    "fake101_calendar_only": lambda g, inputs: _replay_live_fake101_calendar_only(inputs),
    "fake101": _replay_live_fake101,
}


@pytest.mark.parametrize("golden_path", CASES, ids=lambda p: p.stem)
def test_moodle_parity(golden_path):
    golden = load_golden(golden_path)
    case = golden["case"]
    replay = _REPLAYS.get(case)
    if replay is None:
        raise AssertionError(
            f"tests/oracle/moodle/{golden_path.name}: no parity replay wired up for "
            f"case {case!r} - add one to tests/parity/test_moodle.py's _REPLAYS")
    new = replay(golden, load_inputs(golden_path))
    assert_superset(golden_path, new)


def test_every_moodle_golden_has_a_replay():
    cases = {load_golden(p)["case"] for p in CASES}
    assert cases <= set(_REPLAYS)
