from datetime import datetime, timedelta, timezone

from hub.models import Item, status_of

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


def test_within_48h_is_soon():
    assert status_of(item(due=NOW + timedelta(hours=47)), NOW) == "soon"
    assert status_of(item(due=NOW + timedelta(hours=48)), NOW) == "soon"


def test_beyond_48h_is_upcoming():
    assert status_of(item(due=NOW + timedelta(hours=49)), NOW) == "upcoming"
