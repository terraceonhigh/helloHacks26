"""DIVERGENCES.md itself: parses, every entry has real evidence, and every
entry names a golden that exists (a divergence for a deleted case is stale)."""
from tests.parity.superset import ORACLE, load_divergences


def test_divergences_file_is_valid_and_points_at_real_goldens():
    for d in load_divergences():
        assert (ORACLE / d["adapter"] / f"{d['case']}.json").exists(), \
            f"divergence names golden {d['adapter']}/{d['case']}, which doesn't exist"
