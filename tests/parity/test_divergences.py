"""DIVERGENCES.md and the goldens themselves: well-formed, and every listed
divergence names a golden that exists (one for a deleted case is stale)."""
import json

import pytest

from tests.parity.superset import FIXTURES, ORACLE, RECORD_KEYS, assert_superset, load_divergences

GOLDENS = sorted(ORACLE.glob("*/*.json"))


def _cases():
    out = set()
    for p in GOLDENS:
        g = json.loads(p.read_text(encoding="utf-8"))
        adapter = g.get("adapter", p.parent.name)
        out |= {(adapter, p.stem), (adapter, g.get("case") or p.stem)}
    return out


def test_divergences_file_is_valid_and_points_at_real_goldens():
    cases = _cases()
    for d in load_divergences():
        assert (d["adapter"], d["case"]) in cases, \
            f"divergence names golden {d['adapter']}/{d['case']}, which doesn't exist under tests/oracle/"


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_golden_is_wellformed_and_matches_itself(path):
    g = json.loads(path.read_text(encoding="utf-8"))
    assert ("output" in g) != ("result" in g), "a golden has exactly one of output/result"
    for rel in g.get("inputs", []):
        if rel.endswith(".json") and rel.count("/") >= 1 and (ORACLE / rel).exists():
            continue  # query goldens may cite other goldens as their inputs
        assert (FIXTURES / rel).exists(), f"input {rel} missing under tests/fixtures/"
    if "output" in g:
        assert set(g["output"]) <= set(RECORD_KEYS), f"unknown record types {set(g['output']) - set(RECORD_KEYS)}"
        # the comparator must accept the oracle's own output (no divergences involved)
        if not [d for d in load_divergences() if d["adapter"] == g["adapter"] and d["case"] == g.get("case")]:
            assert_superset(g, g["output"])
