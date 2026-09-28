"""Port of main's tests/test_captures.py behaviours (dispatch, JSON-safe
dedup, "unverified source" rejection) for lauds.adapters.captures. Most of
main's own cases hard-code "canvas" as the example provider; canvas isn't
this task's adapter (and may not be ported into this checkout yet), so the
dispatch/dedup behaviour is exercised against a small fake registered
adapter instead - it's captures.py's own logic under test, not any one
provider's parse_capture. One real end-to-end case uses
lauds.adapters.piazza (this task's own, always available)."""
import pytest

from lauds import adapters
from lauds.adapters import _captures as captures
from lauds.models import Bundle, Course, Item

DUE = "2026-09-30T06:59:00+00:00"


def _fake_parse_capture(capture):
    course = Course("CPSC 121", "", "", "Models", source="fakesrc")
    from datetime import datetime

    item = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
                due=datetime.fromisoformat(DUE), url="https://x/quiz/3", source="fakesrc")
    # Two identical rows (e.g. two capture snapshots of the same planner
    # entry): normalize() must dedupe by (source, url); parse() itself does not.
    return Bundle(courses=[course], items=[item, item])


@pytest.fixture
def fake_source(monkeypatch):
    """Registers "fakesrc" alongside whatever's really discovered, standing
    in for a real provider adapter without depending on one being ported."""
    fake = type("FakeAdapter", (), {"NAME": "fakesrc", "fetch": staticmethod(lambda **kw: Bundle()),
                                     "parse_capture": staticmethod(_fake_parse_capture)})
    real_get = adapters.get
    monkeypatch.setattr(adapters, "get", lambda name: fake if name == "fakesrc" else real_get(name))
    real_names = adapters.names
    monkeypatch.setattr(adapters, "names", lambda: sorted({*real_names(), "fakesrc"}))
    return fake


def test_capture_dispatch_uses_the_registered_adapters_parse_capture(fake_source):
    bundle = captures.parse({"source": "fakesrc"})
    assert [c.code for c in bundle.courses] == ["CPSC 121"]
    assert len(bundle.items) == 2  # parse() itself doesn't dedupe - normalize() does


def test_normalize_returns_json_safe_identity_deduped_shared_rows(fake_source):
    result = captures.normalize({"source": "fakesrc"})
    assert result == {
        "source": "fakesrc",
        "stored": False,
        "courses": [{"code": "CPSC 121", "grade": None, "section": "", "term": "", "title": "Models"}],
        "items": [{"category": "deadline", "course": "CPSC 121", "done": None, "due": DUE, "files": [],
                   "kind": "quiz", "source": "fakesrc", "title": "Quiz 2", "url": "https://x/quiz/3"}],
    }


@pytest.mark.parametrize("capture", [None, [], {"source": "../db"}, {"source": "missing_provider"},
                                      {"source": "site"}])
def test_capture_dispatch_rejects_unverified_sources(capture):
    with pytest.raises(ValueError):
        captures.parse(capture)


def test_capture_dispatch_rejects_a_source_with_no_parse_capture(monkeypatch):
    fake = type("NoParseAdapter", (), {"NAME": "nopcap", "fetch": staticmethod(lambda **kw: Bundle())})
    real_get = adapters.get
    monkeypatch.setattr(adapters, "get", lambda name: fake if name == "nopcap" else real_get(name))
    with pytest.raises(ValueError, match="no verified adapter"):
        captures.parse({"source": "nopcap"})


def test_dispatch_accepts_an_adapter_that_still_returns_a_courses_items_tuple(monkeypatch):
    """captures.py's own contract prefers a Bundle, but tolerates an adapter
    whose parse_capture kept main's (courses, items) tuple shape."""
    course = Course("CPSC 121", "", "", "Models", source="tuplesrc")
    fake = type("TupleAdapter", (), {"NAME": "tuplesrc", "fetch": staticmethod(lambda **kw: Bundle()),
                                      "parse_capture": staticmethod(lambda capture: ([course], []))})
    real_get = adapters.get
    monkeypatch.setattr(adapters, "get", lambda name: fake if name == "tuplesrc" else real_get(name))
    bundle = captures.parse({"source": "tuplesrc"})
    assert isinstance(bundle, Bundle) and bundle.courses == [course]


def test_piazza_capture_end_to_end_through_the_real_dispatcher():
    result = captures.normalize({"source": "piazza", "networks": [{
        "id": "abc123", "course_number": "CPSC 121", "name": "Models", "term": "Fall 2026",
        "posts": [{"id": "post123", "tags": ["pin"], "bucket_name": "Pinned",
                   "history": [{"subject": "Quiz room"}]}],
    }]})
    assert result["source"] == "piazza" and result["stored"] is False
    assert result["courses"][0]["code"] == "CPSC 121"
    assert result["items"][0]["title"] == "Quiz room"
    assert result["items"][0]["source"] == "piazza"
