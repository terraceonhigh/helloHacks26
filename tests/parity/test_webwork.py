"""Parity-to-superset for lauds.adapters.webwork against every golden under
tests/oracle/webwork/*.json (offline and live_).

Each webwork golden's `output` was produced by main's `to_item()` over raw
`<li>` fragment(s) with a specific per-row `base` (or none) -- the fragments
themselves don't carry that base, so it's replayed here exactly as the
oracle harvest used it (tools/harvest_oracle.py's `harvest_webwork`, itself
a port of tests/test_webwork.py's own per-test bases). `live_selfhost` is a
real full page instead, and goes through the adapter's own page-level parser.
"""
import json
import re

import pytest

from lauds.adapters.webwork import parse_problem_sets, parse_row
from lauds.models import Bundle
from tests.parity.superset import FIXTURES, golden_paths, load_inputs, assert_superset

GOLDENS = golden_paths("webwork")

# problem_set_rows: golden inputs, in order, each with the exact base the
# oracle harvest used for that row (see tools/harvest_oracle.py:harvest_webwork,
# itself replaying tests/test_webwork.py's own per-test bases).
_PROBLEM_SET_ROW_BASES = {
    "webwork/open_row.html": "https://webwork.example.edu/",
    "webwork/not_open_row.html": "https://webwork.example.edu/webwork2/MATH_101",
    "webwork/past_due_with_date_row.html": "https://webwork.example.edu/",
    "webwork/past_due_no_date_row.html": "",
    "webwork/quiz_row.html": "",
}


def _bundle_for(golden: dict) -> Bundle:
    case = golden["case"]
    course_code = "MATH 101"

    if case == "problem_set_rows":
        inputs = load_inputs(golden)
        items = [parse_row(text, course_code, base=_PROBLEM_SET_ROW_BASES[rel])
                 for rel, text in inputs.items()]
        return Bundle(items=items)

    if case == "two_not_open_sets_distinct_urls":
        # The golden's only input is a JSON descriptor of the two set names
        # (see tests/fixtures/webwork/two_not_open_sets.json); the actual
        # regression is two "not-open" rows sharing one course, built from
        # the same template the oracle harvest used (not_open_row.html with
        # its set name swapped) -- see tools/harvest_oracle.py:harvest_webwork.
        base = "https://webwork.example.edu/webwork2/MATH_101"
        row_a = (FIXTURES / "webwork" / "not_open_row.html").read_text(encoding="utf-8")
        row_b = row_a.replace(">HW2<", ">HW3<")
        return Bundle(items=[parse_row(row_a, course_code, base=base),
                              parse_row(row_b, course_code, base=base)])

    # live_selfhost (or any future full-page golden): a real Assignments page.
    extra = golden.get("extra", {})
    inputs = load_inputs(golden)
    (raw,) = inputs.values()
    raw = _unredact_effective_user(raw, golden)
    return Bundle(items=parse_problem_sets(raw, extra.get("course_code", course_code), extra.get("base", "")))


def _unredact_effective_user(raw: str, golden: dict) -> str:
    """The committed live fixture has its session's `effectiveUser` query
    param replaced with "REDACTED" by the live harvester's SecretScrubber
    (tests/live/README.md's "Secrets handling"), which ran *after* the
    golden's own `output` was captured from the real, unscrubbed page -- so
    the golden's item urls still carry the real value. Recover it from the
    golden (already committed and public in this repo; nothing new is read
    or disclosed here) so the checked-in fixture can be replayed byte-for-
    byte against it, instead of failing parity on a redaction artifact that
    has nothing to do with whether the adapter's mapping is correct."""
    urls = " ".join(i.get("url", "") for i in golden.get("output", {}).get("items", []))
    m = re.search(r"effectiveUser=([^&\"'\s]+)", urls)
    if m and m.group(1) != "REDACTED":
        return raw.replace("effectiveUser=REDACTED", f"effectiveUser={m.group(1)}")
    return raw


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_webwork_parity(path):
    golden = json.loads(path.read_text(encoding="utf-8"))
    assert_superset(golden, _bundle_for(golden))
