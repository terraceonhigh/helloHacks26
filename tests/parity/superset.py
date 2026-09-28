"""The parity-to-superset comparator (BRIEF.md, "THE acceptance test").

    assert_superset(golden, new)

`golden` is a path to (or the loaded dict of) a file under tests/oracle/.
`new` is what lauds produced for the same inputs:

- adapter golden (has "output"): a lauds Bundle, or a {courses, items,
  textbooks, meetings} dict of model objects or of main-shaped dicts.
  Projected through lauds.compat before comparing.
- query golden (has "result"): the lauds store query's return value
  (list of row tuples, or by_course's dict), or whatever the golden's query
  returns (e.g. a list of statuses).

The rule, exactly:
1. Records are matched by identity - items (source, url); courses
   (code, section, term); textbooks (course, isbn); meetings (course, kind,
   days, start_time, term_start, source); query rows by their query's
   natural key. Every oracle record must be present. Extras are allowed.
2. Every oracle field that is non-empty (not None, "", [] or {}) must equal
   the new value exactly. Oracle-empty fields accept anything. New fields
   are always allowed (dict keys / trailing row columns).
3. Ordering is checked only where main promised it: upcoming() (and each
   by_course group) is chronological by due.
4. A difference passes only if DIVERGENCES.md's ```json block lists it -
   {adapter, case, key, field, oracle, new, evidence, reason} matching
   exactly (a missing record is field "*", oracle = the whole oracle
   record, new = null). A listed divergence that this comparison didn't need
   also fails: no stale excuses.

Never loosen this file to make a parity test pass (BRIEF.md rule 6).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from lauds.compat import bundle_to_main, jsonable

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
ORACLE = REPO / "tests" / "oracle"
DIVERGENCES = REPO / "DIVERGENCES.md"

DIVERGENCE_FIELDS = ("adapter", "case", "key", "field", "oracle", "new", "evidence", "reason")

RECORD_KEYS = {
    "items": ("source", "url"),
    "courses": ("code", "section", "term"),
    "textbooks": ("course", "isbn"),
    "meetings": ("course", "kind", "days", "start_time", "term_start", "source"),
}

# Query row layouts (main's hub/db.py) -> column names and identity columns.
_ITEM_ROW = ("code", "category", "kind", "title", "due", "url", "done", "source")
QUERY_ROWS = {
    "upcoming": (_ITEM_ROW, ("source", "url")),
    "undated": (_ITEM_ROW, ("source", "url")),
    "by_course": (_ITEM_ROW, ("source", "url")),
    "courses": (("code", "term", "title", "grade"), ("code", "term")),
    "textbooks": (("code", "title", "isbn", "required", "price", "url"), ("code", "isbn")),
    "schedule": (("code", "kind", "days", "start_time", "end_time", "location", "term_start", "term_end", "source"),
                 ("code", "kind", "days", "start_time", "term_start", "source")),
}
ORDERED_BY_DUE = {"upcoming", "by_course"}


# --- loading ---------------------------------------------------------------

def load_golden(golden) -> dict:
    if isinstance(golden, dict):
        return golden
    return json.loads(Path(golden).read_text(encoding="utf-8"))


def golden_paths(adapter: str, root: Path = ORACLE) -> list[Path]:
    """Every golden for one adapter, sorted - for pytest.mark.parametrize."""
    return sorted((Path(root) / adapter).glob("*.json"))


def load_inputs(golden, fixtures_root: Path = FIXTURES) -> dict:
    """The golden's raw inputs, {relative path: content}, in the golden's
    order. Text files come back as str (utf-8), anything else as bytes."""
    out = {}
    for rel in load_golden(golden).get("inputs", []):
        data = (Path(fixtures_root) / rel).read_bytes()
        try:
            out[rel] = data.decode("utf-8")
        except UnicodeDecodeError:
            out[rel] = data
    return out


def load_divergences(path: Path = DIVERGENCES) -> list[dict]:
    """The first ```json fenced block of DIVERGENCES.md, validated."""
    path = Path(path)
    if not path.exists():
        return []
    m = re.search(r"```json\s*\n(.*?)```", path.read_text(encoding="utf-8"), re.S)
    if not m:
        raise AssertionError(f"{path}: no ```json block found")
    entries = json.loads(m.group(1))
    if not isinstance(entries, list):
        raise AssertionError(f"{path}: the json block must be a list")
    for n, e in enumerate(entries):
        missing = [f for f in DIVERGENCE_FIELDS if f not in e]
        if missing:
            raise AssertionError(f"{path}: divergence #{n} is missing {missing}")
        if not str(e["reason"]).strip():
            raise AssertionError(f"{path}: divergence #{n} has no reason")
        ev = e["evidence"] if isinstance(e["evidence"], list) else [e["evidence"]]
        if not ev or not all(isinstance(p, str) and p.strip() for p in ev):
            raise AssertionError(f"{path}: divergence #{n} has no evidence path")
        for p in ev:
            if not (REPO / p).exists() and not (path.parent / p).exists():
                raise AssertionError(f"{path}: divergence #{n} evidence {p!r} does not exist")
    return entries


# --- comparing -------------------------------------------------------------

def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _norm(v):
    """JSON round trip: tuples -> lists, datetimes -> ISO, so both sides compare alike."""
    return json.loads(json.dumps(jsonable(v)))


class _Problems:
    def __init__(self, adapter, case, divergences):
        self.adapter, self.case = adapter, case
        self.mine = [d for d in divergences if d["adapter"] == adapter and d["case"] == case]
        self.used = set()
        self.failures = []

    def diff(self, what, key, field, oracle, new, message):
        oracle, new = _norm(oracle), _norm(new)
        for n, d in enumerate(self.mine):
            if (_norm(d["key"]) == _norm(list(key)) and d["field"] == field
                    and _norm(d["oracle"]) == oracle and _norm(d["new"]) == new):
                self.used.add(n)
                return
        self.failures.append(f"[{self.adapter}/{self.case}] {what} key={json.dumps(list(key))} "
                             f"field={field!r}: {message}\n    oracle: {json.dumps(oracle)[:500]}"
                             f"\n    new:    {json.dumps(new)[:500]}")

    def finish(self):
        for n, d in enumerate(self.mine):
            if n not in self.used:
                self.failures.append(
                    f"[{self.adapter}/{self.case}] STALE divergence (listed in DIVERGENCES.md but not needed): "
                    f"key={json.dumps(d['key'])} field={d['field']!r} - remove it or fix the mismatch it expects")
        if self.failures:
            raise AssertionError(f"{len(self.failures)} parity failure(s):\n" + "\n".join(self.failures))


def _match_records(p, what, oracle_recs, new_recs, key_of, fields_of):
    """Rule 1+2 over one list. key_of(rec) -> tuple; fields_of(rec) -> {field: value}."""
    by_key = {}
    for n, r in enumerate(new_recs):
        by_key.setdefault(key_of(r), []).append(n)
    used = set()
    for o in oracle_recs:
        k = key_of(o)
        cands = [n for n in by_key.get(k, []) if n not in used]
        if not cands:
            p.diff(what, k, "*", o, None, "oracle record missing from new output")
            continue
        of = fields_of(o)

        def mismatches(n):
            nf = fields_of(new_recs[n])
            return [(f, v, nf.get(f)) for f, v in of.items() if not _empty(v) and _norm(nf.get(f)) != _norm(v)]

        best = min(cands, key=lambda n: len(mismatches(n)))
        used.add(best)
        for f, ov, nv in mismatches(best):
            p.diff(what, k, f, ov, nv, "field differs")


def _dict_key(names):
    return lambda r: tuple(_norm_key(r.get(n)) for n in names)


def _norm_key(v):
    v = _norm(v)
    return tuple(v) if isinstance(v, list) else v


def _check_due_order(p, what, rows, due_index):
    dues = [r[due_index] for r in rows if len(r) > due_index and r[due_index] is not None]
    try:
        parsed = [datetime.fromisoformat(d) for d in dues]
        if len({d.tzinfo is None for d in parsed}) > 1:
            raise TypeError
        seq = parsed
    except (TypeError, ValueError):
        seq = dues
    for a, b, da, db in zip(seq, seq[1:], dues, dues[1:]):
        if b < a:
            p.diff(what, ("order",), "due", "chronological", [da, db], "rows not sorted by due (main promised this)")
            return


def _compare_rows(p, qname, oracle_rows, new_rows, group=None):
    names, key_names = QUERY_ROWS[qname]
    idx = {n: i for i, n in enumerate(names)}

    def as_fields(row):
        return {names[i] if i < len(names) else str(i): v for i, v in enumerate(row)}

    def key_of(row):
        f = as_fields(row)
        k = tuple(_norm_key(f.get(n)) for n in key_names)
        return (group, *k) if group is not None else k

    oracle_rows, new_rows = _norm(oracle_rows), _norm(list(new_rows))
    _match_records(p, f"{qname} row", oracle_rows, new_rows, key_of, as_fields)
    if qname in ORDERED_BY_DUE:
        _check_due_order(p, f"{qname} order" + (f" [{group}]" if group else ""), new_rows, idx["due"])


def _generic_result(p, qname, oracle, new):
    """A query golden whose shape we don't know: every oracle element must be
    present in new; a dict element with source+url is matched by those."""
    oracle, new = _norm(oracle), _norm(new)
    if not isinstance(oracle, list):
        if oracle != new and not _empty(oracle):
            p.diff(qname, ("result",), "*", oracle, new, "result differs")
        return
    new = new if isinstance(new, list) else [new]

    def key_of(e):
        if isinstance(e, dict) and "source" in e and "url" in e:
            return (e["source"], e["url"])
        return (json.dumps(e, sort_keys=True),)

    def fields_of(e):
        return e if isinstance(e, dict) else {"value": e}

    _match_records(p, f"{qname} element", oracle, new, key_of, fields_of)


def query_name(query: str) -> str:
    m = re.search(r"(\w+)\s*\(", query or "")
    return m.group(1) if m else (query or "")


def assert_superset(golden, new, divergences_path: Path = DIVERGENCES):
    g = load_golden(golden)
    case = g.get("case") or (Path(golden).stem if not isinstance(golden, dict) else "?")
    if "output" in g:
        adapter = g["adapter"]
        p = _Problems(adapter, case, load_divergences(divergences_path))
        new_main = bundle_to_main(new)
        for kind, oracle_recs in g["output"].items():
            if kind not in RECORD_KEYS:
                raise AssertionError(f"[{adapter}/{case}] golden has unknown record type {kind!r}")
            _match_records(p, kind[:-1], oracle_recs, new_main.get(kind) or [],
                           _dict_key(RECORD_KEYS[kind]), lambda r: r)
    elif "result" in g:
        adapter = g.get("adapter", "queries")
        p = _Problems(adapter, case, load_divergences(divergences_path))
        qname = query_name(g.get("query", ""))
        oracle = g["result"]
        if qname == "by_course" and isinstance(oracle, dict):
            new = _norm(new) if isinstance(new, dict) else {}
            for code, rows in oracle.items():
                if code not in new:
                    p.diff("by_course group", (code,), "*", rows, None, "course group missing")
                    continue
                _compare_rows(p, qname, rows, new[code], group=code)
        elif qname in QUERY_ROWS and isinstance(oracle, list):
            _compare_rows(p, qname, oracle, new)
        else:
            _generic_result(p, qname, oracle, new)
    else:
        raise AssertionError(f"{golden}: neither 'output' nor 'result' - not a golden")
    p.finish()
