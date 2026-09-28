"""Parity-to-superset for the Brightspace adapter: every golden under
tests/oracle/brightspace/, replayed through lauds.adapters.brightspace.to_course.
"""
import json

import pytest

from lauds.adapters import brightspace
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

CASES = golden_paths("brightspace")


def _replay_to_course_mapping(inputs):
    data = json.loads(inputs["brightspace/myenrollments_items.json"])
    courses = [brightspace.to_course(item) for item in data["page1"] + data["page2"]]
    return {"courses": courses}


_REPLAYS = {
    "to_course_mapping": lambda g, inputs: _replay_to_course_mapping(inputs),
}


@pytest.mark.parametrize("golden_path", CASES, ids=lambda p: p.stem)
def test_brightspace_parity(golden_path):
    golden = load_golden(golden_path)
    case = golden["case"]
    replay = _REPLAYS.get(case)
    if replay is None:
        raise AssertionError(
            f"tests/oracle/brightspace/{golden_path.name}: no parity replay wired up for "
            f"case {case!r} - add one to tests/parity/test_brightspace.py's _REPLAYS")
    new = replay(golden, load_inputs(golden_path))
    assert_superset(golden_path, new)


def test_every_brightspace_golden_has_a_replay():
    cases = {load_golden(p)["case"] for p in CASES}
    assert cases <= set(_REPLAYS)
