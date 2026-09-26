from datetime import datetime, timedelta, timezone

from hub.urgency_model import predict_urgency

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def test_no_due_date_is_low():
    assert predict_urgency("Reading 4", None, NOW) == "low"


def test_returns_a_known_label():
    label = predict_urgency("Midterm Exam 1", NOW + timedelta(days=2), NOW)
    assert label in ("overdue", "critical", "high", "medium", "low")


def test_overdue_detected():
    assert predict_urgency("PS3", NOW - timedelta(days=1), NOW) in ("overdue", "critical", "high")
