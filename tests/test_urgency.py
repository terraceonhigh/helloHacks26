from datetime import datetime, timedelta, timezone

from hub.models import classify_urgency

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def test_no_due_date_is_low():
    assert classify_urgency("read chapter 3", None, NOW) == "low"


def test_past_due_is_overdue():
    assert classify_urgency("quiz 1", NOW - timedelta(hours=1), NOW) == "overdue"


def test_final_due_soon_is_critical():
    assert classify_urgency("Final exam", NOW + timedelta(hours=6), NOW) == "critical"


def test_reading_due_in_a_week_is_low():
    assert classify_urgency("weekly reading", NOW + timedelta(days=7), NOW) == "low"


def test_quiz_due_tomorrow_is_medium_or_higher():
    assert classify_urgency("Quiz 2", NOW + timedelta(hours=24), NOW) in ("medium", "high", "critical")
