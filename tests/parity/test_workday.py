"""Parity-to-superset for the workday adapter: every golden under
tests/oracle/workday/ is a real xlsx export (or - for the kind-mapping case -
several tiny ones concatenated, per that golden's own "extra" note), run
through lauds.adapters.workday and checked against main's oracle output."""
import re

import pytest

from lauds.adapters import workday
from lauds.models import Bundle
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

GOLDENS = golden_paths("workday")


def _term(golden):
    m = re.search(r"term='([^']+)'", golden.get("oracle_call", ""))
    return m.group(1) if m else "2026W1"


def _run(golden):
    """Dispatch on the golden's own oracle_call string, which names exactly
    one of our two pure functions - so a new golden for either one is picked
    up automatically without a per-case table."""
    inputs = load_inputs(golden)
    term = _term(golden)
    call = golden["oracle_call"]
    if "parse_workday_courses" in call:
        courses = []
        for rel in golden["inputs"]:
            courses += workday.parse_courses(inputs[rel], term)
        return Bundle(courses=courses)
    if "parse_workday_schedule" in call:
        meetings = []
        for rel in golden["inputs"]:
            meetings += workday.parse_schedule(inputs[rel], term)
        return Bundle(meetings=meetings)
    raise NotImplementedError(f"don't know how to run oracle_call {call!r}")


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_parity(path):
    golden = load_golden(path)
    assert_superset(golden, _run(golden))
