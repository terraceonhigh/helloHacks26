"""The comparator must catch every way a port can regress (BRIEF.md rule 1-5)."""
import json
from datetime import datetime, timezone

import pytest

from lauds.compat import to_main
from lauds.models import Bundle, Course, Item
from tests.parity.superset import assert_superset, load_divergences, load_inputs

DUE = datetime(2026, 10, 1, 23, 59, tzinfo=timezone.utc)


def item(url="https://x/a/1", **kw):
    base = dict(course="CPSC 121", category="task", kind="assignment", title="PS1", due=DUE, url=url, source="canvas")
    return Item(**{**base, **kw})


def golden(items, courses=None, case="c1"):
    out = {"items": [to_main(i) for i in items]}
    if courses is not None:
        out["courses"] = [to_main(c) for c in courses]
    return {"adapter": "canvas", "case": case, "inputs": [], "oracle_call": "t", "now": None, "extra": {}, "output": out}


def divfile(tmp_path, entries):
    (tmp_path / "ev.json").write_text("{}")
    for e in entries:
        e.setdefault("evidence", str(tmp_path / "ev.json"))
        e.setdefault("reason", "evidence shows the oracle was wrong")
    p = tmp_path / "DIVERGENCES.md"
    p.write_text("# d\n\n```json\n" + json.dumps(entries) + "\n```\n")
    return p


@pytest.fixture
def nodiv(tmp_path):
    return divfile(tmp_path, [])


def test_identical_passes(nodiv):
    assert_superset(golden([item()]), Bundle(items=[item()]), nodiv)


def test_missing_record_fails(nodiv):
    with pytest.raises(AssertionError, match=r"missing.*|key=\[\"canvas\", \"https://x/a/2\"\]"):
        assert_superset(golden([item(), item("https://x/a/2")]), Bundle(items=[item()]), nodiv)


def test_missing_record_type_fails(nodiv):
    with pytest.raises(AssertionError, match="course"):
        assert_superset(golden([item()], courses=[Course("CPSC 121", "101", "2026W1", "Models")]),
                        Bundle(items=[item()]), nodiv)


def test_changed_value_fails_and_names_the_field(nodiv):
    with pytest.raises(AssertionError, match=r"\[canvas/c1\].*field='title'"):
        assert_superset(golden([item()]), Bundle(items=[item(title="PS1 (late)")]), nodiv)


def test_changed_offset_is_a_changed_value(nodiv):
    from datetime import timedelta
    same_instant = DUE.astimezone(timezone(timedelta(hours=-7)))
    with pytest.raises(AssertionError, match="field='due'"):
        assert_superset(golden([item()]), Bundle(items=[item(due=same_instant)]), nodiv)


def test_extra_records_and_extra_fields_pass(nodiv):
    new = Bundle(items=[item(description="more", points=10.0), item("https://x/extra")],
                 courses=[Course("CPSC 121", "", "", "x")])
    assert_superset(golden([item()]), new, nodiv)


def test_oracle_none_or_empty_fields_accept_anything(nodiv):
    g = golden([item(done=None, due=None, title="")])
    assert_superset(g, Bundle(items=[item(done=True, title="Real title")]), nodiv)


def test_oracle_false_is_a_value_not_empty(nodiv):
    with pytest.raises(AssertionError, match="field='done'"):
        assert_superset(golden([item(done=False)]), Bundle(items=[item(done=True)]), nodiv)


def test_unlisted_divergence_fails_listed_one_passes(tmp_path):
    g = golden([item()])
    new = Bundle(items=[item(title="PS1 fixed")])
    with pytest.raises(AssertionError):
        assert_superset(g, new, divfile(tmp_path, []))
    listed = divfile(tmp_path, [{"adapter": "canvas", "case": "c1", "key": ["canvas", "https://x/a/1"],
                                 "field": "title", "oracle": "PS1", "new": "PS1 fixed"}])
    assert_superset(g, new, listed)


def test_divergence_must_match_values_exactly(tmp_path):
    listed = divfile(tmp_path, [{"adapter": "canvas", "case": "c1", "key": ["canvas", "https://x/a/1"],
                                 "field": "title", "oracle": "PS1", "new": "something else"}])
    with pytest.raises(AssertionError):
        assert_superset(golden([item()]), Bundle(items=[item(title="PS1 fixed")]), listed)


def test_stale_divergence_fails(tmp_path):
    listed = divfile(tmp_path, [{"adapter": "canvas", "case": "c1", "key": ["canvas", "https://x/a/1"],
                                 "field": "title", "oracle": "PS1", "new": "PS1 fixed"}])
    with pytest.raises(AssertionError, match="STALE"):
        assert_superset(golden([item()]), Bundle(items=[item()]), listed)


def test_missing_record_divergence_uses_star_field(tmp_path):
    g = golden([item(), item("https://x/bogus")])
    listed = divfile(tmp_path, [{"adapter": "canvas", "case": "c1", "key": ["canvas", "https://x/bogus"],
                                 "field": "*", "oracle": to_main(item("https://x/bogus")), "new": None}])
    assert_superset(g, Bundle(items=[item()]), listed)


def test_divergence_without_real_evidence_is_rejected(tmp_path):
    p = divfile(tmp_path, [{"adapter": "a", "case": "c", "key": [], "field": "f", "oracle": 1, "new": 2,
                            "evidence": "does/not/exist.json"}])
    with pytest.raises(AssertionError, match="evidence"):
        load_divergences(p)


def test_main_shaped_dicts_are_accepted_as_new(nodiv):
    assert_superset(golden([item()]), {"items": [to_main(item())]}, nodiv)


# --- query goldens ---------------------------------------------------------

ROW = ["CPSC 121", "task", "assignment", "PS1", "2026-10-01T23:59:00+00:00", "https://x/a/1", None, "canvas"]


def qgolden(result, query="db.upcoming(conn)"):
    return {"query": query, "now": None, "inputs": [], "result": result, "case": "q1"}


def test_query_rows_superset_with_trailing_columns(nodiv):
    assert_superset(qgolden([ROW]), [tuple(ROW) + (42,)], nodiv)


def test_query_row_changed_value_fails(nodiv):
    with pytest.raises(AssertionError, match="field='title'"):
        assert_superset(qgolden([ROW]), [tuple(ROW[:3] + ["PS9"] + ROW[4:])], nodiv)


def test_query_row_missing_fails(nodiv):
    with pytest.raises(AssertionError, match="missing"):
        assert_superset(qgolden([ROW]), [], nodiv)


def test_upcoming_must_be_chronological(nodiv):
    later = ROW[:4] + ["2026-10-02T00:00:00-07:00", "https://x/a/2"] + ROW[6:]
    assert_superset(qgolden([ROW, later]), [ROW, later], nodiv)
    with pytest.raises(AssertionError, match="sorted by due"):
        assert_superset(qgolden([ROW, later]), [later, ROW], nodiv)


def test_by_course_groups(nodiv):
    g = qgolden({"CPSC 121": [ROW]}, "db.by_course(conn)")
    assert_superset(g, {"CPSC 121": [tuple(ROW)], "MATH 100": []}, nodiv)
    with pytest.raises(AssertionError, match="group missing"):
        assert_superset(g, {}, nodiv)


def test_generic_query_result(nodiv):
    g = qgolden([{"source": "canvas", "url": "u", "status": "soon"}], "models.status_of(item, now)")
    assert_superset(g, [{"source": "canvas", "url": "u", "status": "soon", "x": 1}], nodiv)
    with pytest.raises(AssertionError, match="field='status'"):
        assert_superset(g, [{"source": "canvas", "url": "u", "status": "overdue"}], nodiv)


def test_load_inputs_reads_text_and_bytes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.json").write_text('{"k": 1}')
    (tmp_path / "a" / "y.xlsx").write_bytes(b"\xff\xfe\x00bin")
    got = load_inputs({"inputs": ["a/x.json", "a/y.xlsx"]}, fixtures_root=tmp_path)
    assert got == {"a/x.json": '{"k": 1}', "a/y.xlsx": b"\xff\xfe\x00bin"}
