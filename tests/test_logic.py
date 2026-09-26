from datetime import datetime, timedelta, timezone

from hub.logic import sort_items

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def row(title, due_offset_hours):
    due = (NOW + timedelta(hours=due_offset_hours)).isoformat()
    return ("CPSC 121", "task", "assignment", title, due, "https://x", None)


def test_overdue_beats_everything():
    rows = [row("Reading 4", 5), row("Final Exam", -1)]
    assert sort_items(rows, NOW)[0][3] == "Final Exam"


def test_critical_beats_low_even_if_further_out():
    rows = [row("Optional practice quiz, 0%", 2), row("Final exam", 20)]
    ordered = sort_items(rows, NOW)
    assert ordered[0][3] == "Final exam"
