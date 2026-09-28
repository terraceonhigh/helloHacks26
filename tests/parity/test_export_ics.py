"""Parity for lauds/export_ics.py (a port of main's hub/export_ics.py)
against tests/oracle/export_ics/*.json.

Each golden is a "result" golden whose whole `result` dict is compared by
plain equality (tests/parity/superset.py's `_generic_result`, since
`to_ics(...)` isn't one of the named `hub.db` queries) - so `new` here must
be built in exactly the golden's own shape, including `round_trip_items`:
a minimal, test-only re-parse of the produced .ics text (course from the
"Title [COURSE]" bracket, kind from CATEGORIES, source from the UID
prefix) - just enough to check to_ics()'s own round-trip promise. A real
inbound Canvas .ics parser is the canvas_ics adapter's job, not this file's.
"""
import json
import re

import pytest
from icalendar import Calendar

from lauds.compat import jsonable
from lauds.export_ics import color_for_kind, known_kinds, to_ics, uid_for
from lauds.models import Item, category_for
from tests.parity.superset import FIXTURES, golden_paths, load_golden

CASES = golden_paths("export_ics")


def _load_items(golden):
    raw = json.loads((FIXTURES / "export_ics" / "items.json").read_text(encoding="utf-8"))
    items = {}
    for key, d in raw.items():
        items[key] = Item(course=d["course"], category=d["category"], kind=d["kind"], title=d["title"],
                           due=None if d["due"] is None else __import__("datetime").datetime.fromisoformat(d["due"]),
                           url=d["url"], source=d["source"], done=d["done"])
    return items


# main's hub/ics.py _kind_and_id/COURSE_SUFFIX, just enough to check
# to_ics()'s own round-trip promise (a real inbound parser, for a real
# Canvas-shaped UID, is the canvas_ics adapter's job, not this file's):
# our own UID ("<source>-<hash>@ubchub") never matches Canvas's own
# "event-assignment-<id>" shape, so main's parser falls back to kind
# "assignment" (or "event" if the url contains "/calendar_events/") and
# leaves the url untouched (no item id to rebuild a deep link from).
_COURSE_SUFFIX = re.compile(r"\s*\[([^\[\]]+)\]\s*$")
_UID_RE = re.compile(r"^event-(assignment|calendar-event)-(\d+)$")


def _kind_for(uid, url):
    m = _UID_RE.match(uid)
    if m:
        return "assignment" if m.group(1) == "assignment" else "event"
    return "event" if "/calendar_events/" in url else "assignment"


def _round_trip(ics_bytes):
    cal = Calendar.from_ical(ics_bytes)
    out = []
    for comp in cal.walk("VEVENT"):
        summary = str(comp["summary"])
        url = str(comp["url"]) if comp.get("url") else ""
        m = _COURSE_SUFFIX.search(summary)
        kind = _kind_for(str(comp["uid"]), url)
        out.append({"category": category_for(kind), "course": m.group(1) if m else "", "done": None,
                    "due": jsonable(comp["dtstart"].dt), "files": [], "kind": kind,
                    "source": str(comp["uid"]).split("-", 1)[0], "title": _COURSE_SUFFIX.sub("", summary),
                    "url": url})
    return out


@pytest.mark.parametrize("golden", CASES, ids=lambda p: p.stem)
def test_export_ics_parity(golden):
    g = load_golden(golden)
    items_by_key = _load_items(g)

    call = g["query"]  # e.g. "hub.export_ics.to_ics([item_a, item_b, item_no_due])"
    keys = re.findall(r"item_\w+", call)
    kind_match = re.search(r"kind=['\"](\w+)['\"]", call)
    kind = kind_match.group(1) if kind_match else None
    items = [items_by_key[k] for k in keys]

    ics = to_ics(items, kind=kind)
    result = {"ics": ics.decode()}
    if "known_kinds" in g["result"]:  # only the richest case checks these extras
        result["known_kinds"] = known_kinds(items)
        result["round_trip_items"] = _round_trip(ics)
        for k in ("exam", "quiz"):
            result[f"color_{k}"] = color_for_kind(k)
        result["color_fallback"] = color_for_kind("__never_seen__")
        result["color_unknown_kind"] = color_for_kind("__never_seen__")
        result["uid_a"] = uid_for(items_by_key["item_a"])
        result["uid_b"] = uid_for(items_by_key["item_b"])

    from tests.parity.superset import assert_superset
    assert_superset(golden, result)
