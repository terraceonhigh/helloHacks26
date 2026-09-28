"""Parity-to-superset for the UBC key dates adapter: every golden under
tests/oracle/key_dates/, run through lauds.adapters.key_dates at the
golden's own fixed clock and checked against main's oracle output. No raw
fixtures here (key_dates has nothing to parse - see the adapter's own
docstring), so "load its raw inputs" is trivially the empty list every one
of these goldens has."""
import re
from datetime import datetime

import pytest

from lauds.adapters import key_dates
from tests.parity.superset import assert_superset, golden_paths, load_golden

GOLDENS = golden_paths("key_dates")


def _campus(golden):
    if "campus" in golden.get("extra", {}):
        return golden["extra"]["campus"]
    m = re.search(r"fetch\(\s*'([^']+)'", golden["oracle_call"])
    if m:
        return m.group(1)
    raise AssertionError(f"{golden['case']}: can't tell which campus this golden is for")


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_parity(path):
    golden = load_golden(path)
    now = datetime.fromisoformat(golden["now"])
    bundle = key_dates.fetch(campus=_campus(golden), term="2026W1", now=now)
    assert_superset(golden, bundle)
