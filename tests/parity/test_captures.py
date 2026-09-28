"""Parity: lauds.adapters.captures.normalize() against every
tests/oracle/captures/*.json golden ("hub.captures.normalize" - the
`"result"`-shaped goldens with the source/stored/courses/items envelope).

Each golden's capture names its own provider ("canvas", "prairielearn").
captures.py is a pure dispatcher: it only ever succeeds for a source that's
actually registered under lauds/adapters/ - every in-scope adapter is
registered by the end of this branch (BRIEF.md's scope list), so every
golden here must actually exercise the real dispatch, never skip past it.
"""
import json

import pytest

from lauds import adapters
from lauds.adapters import _captures as captures
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
    # BRIEF major finding: a conditional pytest.skip here would turn a
    # source whose adapter module fails to import (adapters._discover puts
    # it in load_errors instead of the registry) into a silent skip instead
    # of a failure - it doesn't trigger today (every in-scope adapter loads
    # clean), but the hole stays latent as long as this can skip at all.
    assert source in adapters.names(), (
        f"{path.name}: {source!r} adapter not registered "
        f"(load error: {adapters.load_errors.get(source)})")
    assert_superset(golden, captures.normalize(capture))


def test_every_captures_golden_was_actually_collected():
    assert len(GOLDENS) == 3
