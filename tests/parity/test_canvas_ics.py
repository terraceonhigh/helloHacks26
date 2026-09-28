"""Parity-to-superset for lauds.adapters.canvas_ics against every golden
under tests/oracle/canvas_ics/*.json. Each golden's single input is raw
.ics text; `source` (which case tags "canvas" vs "moodle") comes from the
golden's own `oracle_call` string, exactly as recorded in the golden.
"""
import json
import re

import pytest

from lauds.adapters.canvas_ics import parse
from lauds.models import Bundle
from tests.parity.superset import golden_paths, load_inputs, assert_superset

GOLDENS = golden_paths("canvas_ics")


def _source_for(golden: dict) -> str:
    m = re.search(r"source=['\"](\w+)['\"]", golden.get("oracle_call", ""))
    if not m:
        raise AssertionError(f"{golden['case']}: can't tell which source() to parse with")
    return m.group(1)


def _bundle_for(golden: dict) -> Bundle:
    (ics_text,) = load_inputs(golden).values()
    return Bundle(items=parse(ics_text, source=_source_for(golden)))


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_canvas_ics_parity(path):
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert_superset(golden, _bundle_for(golden))
