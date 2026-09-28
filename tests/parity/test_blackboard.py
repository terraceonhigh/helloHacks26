"""Parity-to-superset for the Blackboard adapter: every golden under
tests/oracle/blackboard/, replayed through lauds.adapters.blackboard.
"""
import json

import pytest

from lauds.adapters import blackboard
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

CASES = golden_paths("blackboard")


def _replay_parse_capture(inputs):
    capture = json.loads(inputs["blackboard/parse_capture.json"])
    courses, items = blackboard.parse_capture(capture)
    return {"courses": courses, "items": items}


def _replay_to_course_missing_term_field(inputs):
    course = json.loads(inputs["blackboard/to_course_no_term.json"])
    return {"courses": [blackboard.to_course(course)]}


_REPLAYS = {
    "parse_capture": lambda g, inputs: _replay_parse_capture(inputs),
    "to_course_missing_term_field": lambda g, inputs: _replay_to_course_missing_term_field(inputs),
}


@pytest.mark.parametrize("golden_path", CASES, ids=lambda p: p.stem)
def test_blackboard_parity(golden_path):
    golden = load_golden(golden_path)
    case = golden["case"]
    replay = _REPLAYS.get(case)
    if replay is None:
        raise AssertionError(
            f"tests/oracle/blackboard/{golden_path.name}: no parity replay wired up for "
            f"case {case!r} - add one to tests/parity/test_blackboard.py's _REPLAYS")
    new = replay(golden, load_inputs(golden_path))
    assert_superset(golden_path, new)


def test_every_blackboard_golden_has_a_replay():
    cases = {load_golden(p)["case"] for p in CASES}
    assert cases <= set(_REPLAYS)
