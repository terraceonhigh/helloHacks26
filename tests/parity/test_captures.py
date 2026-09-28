"""Parity: lauds.adapters.captures.normalize() against every
tests/oracle/captures/*.json golden ("hub.captures.normalize" - the
`"result"`-shaped goldens with the source/stored/courses/items envelope).

Each golden's capture names its own provider ("canvas", "prairielearn").
captures.py is a pure dispatcher: it only ever succeeds for a source that's
actually registered under lauds/adapters/. Piazza (this task's own) is
always registered, so a Piazza-sourced golden always runs for real; a
golden naming a provider ported by a *different* swarm agent is skipped
with a clear, named reason instead of silently "passing" - that's a missing
sibling module, not a captures.py bug, and re-checking after a `git pull`
picks it up the moment that adapter lands.
"""
import json

import pytest

from lauds import adapters
from lauds.adapters import captures
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

GOLDENS = golden_paths("captures")


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_captures_normalize_is_a_superset(path):
    golden = load_golden(path)
    inputs = load_inputs(golden)
    assert len(inputs) == 1, f"{path}: expected exactly one raw input, got {list(inputs)}"
    (capture_text,) = inputs.values()
    capture = json.loads(capture_text)
    source = capture.get("source")
    if source not in adapters.names():
        pytest.skip(f"{path.name}: needs the {source!r} adapter (another swarm agent's porting task), "
                    f"not registered under lauds/adapters/ in this checkout yet")
    assert_superset(golden, captures.normalize(capture))


def test_every_captures_golden_was_actually_collected():
    assert len(GOLDENS) == 3
