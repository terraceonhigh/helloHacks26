"""Turn a browser-extension capture into the shared model.

Provider-specific rules live in `hub/<source>.py` as `parse_capture()`. This
dispatcher never reads provider JSON itself, and adding a provider does not
change the shared ontology or fusion logic.
"""
import importlib
import re
from dataclasses import asdict


_SOURCE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# Explicit allowlist, not just "matches _SOURCE and has parse_capture" - the
# regex alone still lets an anonymous POST to the public /api/normalize
# dynamically import ANY hub.<word> module that happens to exist (PM review
# on #97/#84). Every module here has a reviewed, tested parse_capture().
CAPTURE_SOURCES = frozenset({"canvas", "prairielearn", "moodle", "blackboard", "piazza"})


def parse(capture):
    """Return a provider adapter's (courses, items) from its browser capture."""
    source = capture.get("source") if isinstance(capture, dict) else None
    if not isinstance(source, str) or not _SOURCE.fullmatch(source) or source not in CAPTURE_SOURCES:
        raise ValueError("invalid capture source")
    module_name = f"hub.{source}"
    try:
        adapter = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name == module_name:
            raise ValueError("unsupported capture source") from None
        raise
    parser = getattr(adapter, "parse_capture", None)
    if not callable(parser):
        raise ValueError("capture source has no verified adapter")
    return parser(capture)


def normalize(capture):
    """Provider capture -> JSON-safe shared-model rows, without storing them."""
    courses, items = parse(capture)
    by_identity = {(item.source, item.url): item for item in items}
    return {
        "source": capture["source"],
        "stored": False,
        "courses": [asdict(course) for course in courses],
        "items": [
            {**asdict(item), "due": item.due.isoformat() if item.due else None}
            for item in by_identity.values()
        ],
    }
