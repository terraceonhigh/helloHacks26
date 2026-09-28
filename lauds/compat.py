"""Project lauds records back onto main's hub.models shape.

`to_main(record)` gives exactly what the oracle harvester writes for main's
record (tests/oracle GOLDEN FORMAT): dataclasses.asdict() restricted to main's
fields, datetimes/dates/times as ISO 8601 strings (aware datetimes keep their
offset), tuples/sets as lists, keys sorted. lauds-only fields are dropped.
"""
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time

from lauds import models

# Main's fields per record type - the projection. Anything else is a lauds addition.
MAIN_FIELDS: dict[type, tuple[str, ...]] = {
    models.Course: ("code", "section", "term", "title", "grade"),
    models.Item: ("course", "category", "kind", "title", "due", "url", "source", "done", "files"),
    models.ItemFile: ("name", "url", "kind"),
    models.Textbook: ("course", "title", "isbn", "required", "price", "url"),
    models.Meeting: ("course", "kind", "days", "start_time", "end_time", "location",
                     "term_start", "term_end", "source"),
}

BUNDLE_KEYS = ("courses", "items", "textbooks", "meetings")


def jsonable(value):
    """ISO strings for datetime/date/time, lists for tuples/sets, sorted-key dicts."""
    if isinstance(value, (datetime, date, time)):  # datetime is a date subclass; isoformat covers all
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, set):
        return [jsonable(v) for v in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return to_main(value)
    return value


def to_main(record) -> dict:
    """One lauds model object -> main's asdict shape (sorted keys, ISO strings)."""
    for cls, fields in MAIN_FIELDS.items():
        if isinstance(record, cls):
            d = {name: getattr(record, name) for name in fields}
            if cls is models.Item:
                d["files"] = [to_main(f) for f in record.files]
            return jsonable(d)
    if is_dataclass(record):
        return jsonable(asdict(record))
    raise TypeError(f"to_main: not a lauds model record: {record!r}")


def bundle_to_main(bundle) -> dict:
    """A Bundle (or a {courses, items, textbooks, meetings} dict of model
    objects) -> {"courses": [...], ...} exactly like a golden's "output".
    Dicts already in main's shape pass through (jsonable'd)."""
    if isinstance(bundle, models.Bundle):
        bundle = {k: getattr(bundle, k) for k in BUNDLE_KEYS}
    out = {}
    for key in BUNDLE_KEYS:
        if key in bundle and bundle[key] is not None:
            out[key] = [to_main(r) if is_dataclass(r) else jsonable(r) for r in bundle[key]]
    return out
