"""Turn a browser-extension capture into the shared model.

Port of `hub/captures.py`. That file is a dispatcher: it never reads
provider JSON itself, it looks up `hub.<source>.parse_capture` by the
capture's own `"source"` field and normalizes what comes back. This module
is the same dispatcher, aimed at `lauds.adapters`' plugin registry instead
of `importlib.import_module("hub.<source>")` - discovery already indexes
every adapter by its `NAME`, so reusing it here means a provider only ever
has to define `parse_capture` once, not register it twice.

Not a provider adapter itself: it has no `NAME`/`fetch` of its own (nothing
"captures" from the network). Named with a leading underscore (BRIEF minor
finding: it used to sit in the plugin package as plain `captures.py`, so
`lauds.adapters`' discovery tried to register it as one and logged a
spurious `load_errors["captures"] = "not an adapter"` on every single CLI
run) - `_discover()` skips any module starting with `_`, same as
`lauds/adapters/__init__.py`'s own docstring already says private helpers
do.

`normalize()`'s output only ever depends on whichever adapter the capture
names actually being registered under `lauds/adapters/` - e.g. a Piazza
capture works today; a Canvas or PrairieLearn capture works once that
adapter's own porting task lands `parse_capture` there too.
"""
import re

from lauds import adapters, compat
from lauds.models import Bundle

_SOURCE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def parse(capture: dict) -> Bundle:
    """Return a provider adapter's Bundle for its browser capture. Same
    validation as main's `hub.captures.parse`: an invalid/unverified
    `source` is a `ValueError`, never a crash."""
    source = capture.get("source") if isinstance(capture, dict) else None
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError("invalid capture source")
    try:
        adapter = adapters.get(source)
    except KeyError:
        raise ValueError("unsupported capture source") from None
    parser = getattr(adapter, "parse_capture", None)
    if not callable(parser):
        raise ValueError("capture source has no verified adapter")
    result = parser(capture)
    if isinstance(result, Bundle):
        return result
    courses, items = result  # an adapter that still returns main's (courses, items) shape
    return Bundle(courses=list(courses), items=list(items))


def normalize(capture: dict) -> dict:
    """Provider capture -> JSON-safe shared-model rows, deduped by
    `(source, url)`, without storing them. Records are projected through
    `lauds.compat` to main's shape (golden format) - a lauds-only field
    (description, points, extra, the lauds-only Course fields) never
    reaches this output, matching main's own `asdict()`-shaped result
    exactly on every field main has."""
    bundle = parse(capture)
    by_identity = {(item.source, item.url): item for item in bundle.items}
    main = compat.bundle_to_main(Bundle(courses=bundle.courses, items=list(by_identity.values())))
    return {
        "source": capture["source"],
        "stored": False,
        "courses": main.get("courses", []),
        "items": main.get("items", []),
    }
