"""Parity: lauds.adapters.piazza.parse_capture against every oracle golden
that exercises it - tests/oracle/piazza/*.json (offline, hand-derived from
the real piazza-api client and main's own docstring) plus the Piazza case
under tests/oracle/extension/ (the browser-extension capture, hand-traced
since node is unavailable here, piped through the real
hub.piazza.parse_capture).

Piazza has no public API and nothing self-hostable (unlike Canvas,
PrairieLearn, WeBWorK): every one of these goldens - and this adapter as a
whole - is **fixture-only**. There is no live or docs-verified path
available (see lauds/adapters/piazza.py's module docstring).
"""
import json

import pytest

from lauds.adapters import piazza
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

# The Piazza case lives under tests/oracle/extension/ (its own "adapter"
# field there is "extension" - the shared bucket for every hand-traced
# browser-capture case), so golden_paths("piazza") alone would miss it;
# picked out by its oracle_call naming hub.piazza.parse_capture.
_EXTENSION_PIAZZA_GOLDENS = [
    p for p in golden_paths("extension")
    if "hub.piazza" in (load_golden(p).get("oracle_call") or "")
]

GOLDENS = golden_paths("piazza") + _EXTENSION_PIAZZA_GOLDENS


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_piazza_parse_capture_is_a_superset(path):
    golden = load_golden(path)
    inputs = load_inputs(golden)
    assert len(inputs) == 1, f"{path}: expected exactly one raw input, got {list(inputs)}"
    (capture_text,) = inputs.values()
    bundle = piazza.parse_capture(json.loads(capture_text))
    assert_superset(golden, bundle)


def test_every_piazza_golden_was_actually_collected():
    # A canary against a future rename/move silently dropping a golden from
    # both globs above (BRIEF.md: parametrise so new goldens are picked up
    # automatically - this makes sure "automatically" isn't "accidentally none").
    assert len(golden_paths("piazza")) == 2
    assert len(_EXTENSION_PIAZZA_GOLDENS) == 1
