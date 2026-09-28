"""Every oracle record, rebuilt as a lauds model, projects back to exactly
itself through lauds.compat - so compat can't drift from the golden format."""
import json
from datetime import date, datetime, time

import pytest

from lauds.compat import to_main
from lauds.models import Course, Item, ItemFile, Meeting, Textbook
from tests.parity.superset import ORACLE

GOLDENS = [p for p in sorted(ORACLE.glob("*/*.json")) if "output" in json.loads(p.read_text(encoding="utf-8"))]


def rebuild(kind, r):
    r = dict(r)
    if kind == "items":
        due = r.pop("due")
        due = datetime.fromisoformat(due) if due is not None else None
        r["files"] = [ItemFile(**f) for f in r["files"]]
        item = Item(due=None, **r)
        item.due = due  # set after __post_init__: an oracle naive due is a porter's divergence, not compat's
        return item
    if kind == "meetings":
        for f in ("start_time", "end_time"):
            r[f] = time.fromisoformat(r[f])
        for f in ("term_start", "term_end"):
            r[f] = date.fromisoformat(r[f])
        return Meeting(**r)
    return {"courses": Course, "textbooks": Textbook}[kind](**r)


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_records_round_trip(path):
    for kind, recs in json.loads(path.read_text(encoding="utf-8"))["output"].items():
        for r in recs:
            assert to_main(rebuild(kind, r)) == r
