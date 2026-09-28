"""main's tests/test_models.py behaviours, plus the tz rule and code canonicalising."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from lauds.models import (Bundle, Item, ItemFile, canonical_code, canonical_term, category_for,
                          normalise_course_code, status_of)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def item(due=None, done=None):
    return Item(course="CPSC 121", category="task", kind="assignment", title="x",
                due=due, url="https://x", source="canvas", done=done)


def test_done_wins_over_everything():
    assert status_of(item(due=NOW - timedelta(days=5), done=True), NOW) == "done"


def test_no_due_date_is_upcoming():
    assert status_of(item(due=None), NOW) == "upcoming"


def test_past_due_is_overdue():
    assert status_of(item(due=NOW - timedelta(hours=1)), NOW) == "overdue"


def test_within_48h_is_soon_inclusive():
    assert status_of(item(due=NOW + timedelta(hours=47)), NOW) == "soon"
    assert status_of(item(due=NOW + timedelta(hours=48)), NOW) == "soon"


def test_beyond_48h_is_upcoming():
    assert status_of(item(due=NOW + timedelta(hours=49)), NOW) == "upcoming"


def test_done_false_is_not_done():
    assert status_of(item(due=NOW - timedelta(hours=1), done=False), NOW) == "overdue"


def test_status_compares_instants_across_offsets():
    van = ZoneInfo("America/Vancouver")
    due = datetime(2026, 9, 30, 5, 30, tzinfo=van)  # 12:30 UTC, 30 min after NOW
    assert status_of(item(due=due), NOW) == "soon"
    assert status_of(item(due=due), NOW.astimezone(van)) == "soon"


def test_status_defaults_now_to_the_real_clock():
    assert status_of(item(due=datetime(2000, 1, 1, tzinfo=timezone.utc))) == "overdue"


def test_naive_due_is_rejected():
    with pytest.raises(ValueError, match="tz-aware"):
        item(due=datetime(2026, 9, 30, 12, 0))


def test_files_defaults_to_empty_not_none():
    assert item().files == []


def test_files_hold_entries_with_default_kind():
    i = Item(course="CPSC 121", category="task", kind="assignment", title="PS3", due=None,
             url="https://x", source="canvas", files=[ItemFile(name="handout.pdf", url="https://x/1")])
    assert i.files[0].kind == "file"


def test_positional_construction_matches_main():
    i = Item("CPSC 121", "deadline", "quiz", "Q", None, "https://x", "canvas", True)
    assert (i.done, i.files, i.description, i.points, i.extra) == (True, [], None, None, {})
    assert i.key == ("canvas", "https://x")


@pytest.mark.parametrize("kind,cat", [
    ("assignment", "task"), ("announcement", "task"), ("quiz", "deadline"), ("exam", "deadline"),
    ("event", "deadline"), ("break", "deadline"), ("payment", "deadline"), ("reading", "material"),
    ("textbook", "material"), ("some-new-kind", "task"),
])
def test_category_for(kind, cat):
    assert category_for(kind) == cat


def test_course_codes_canonicalise():
    assert normalise_course_code("CPSC 121 101 2026W1") == ("CPSC", "121", "101")
    assert normalise_course_code("???") == (None, None, None)
    assert canonical_code("cpsc121") == canonical_code("CPSC 121 101 2026W1") == "CPSC 121"
    assert canonical_code("Welcome Hub") == "Welcome Hub"


def test_terms_canonicalise():
    assert canonical_term("2026 Winter Term 1") == "2026W1"
    assert canonical_term("2027 summer term 2") == "2027S2"
    assert canonical_term(None) == canonical_term("  ") == ""
    assert canonical_term("Fall 2026") == "Fall 2026"


def test_bundle_extend():
    b = Bundle(items=[item()]).extend(Bundle(items=[item()]))
    assert len(b.items) == 2 and b.courses == []
