from datetime import date

from hub.sample import SAMPLE_WEEK, load_sample


def test_fixture_sizes():
    courses, items, textbooks = load_sample(today=SAMPLE_WEEK)
    assert len(courses) == 4
    assert len(items) == 15
    assert len(textbooks) == 5


def test_every_item_and_textbook_points_at_a_known_course():
    courses, items, textbooks = load_sample(today=SAMPLE_WEEK)
    keys = {c.key for c in courses}
    assert all(i.course_key in keys for i in items if i.course_key)
    assert all(t.course_key in keys for t in textbooks)


def test_due_dates_are_timezone_aware():
    _, items, _ = load_sample(today=SAMPLE_WEEK)
    assert all(i.due.tzinfo is not None for i in items)


def test_dates_shift_by_whole_weeks():
    _, original, _ = load_sample(today=SAMPLE_WEEK)
    _, shifted, _ = load_sample(today=date(2026, 10, 14))  # a Wednesday, 2 weeks later
    assert (shifted[0].due - original[0].due).days == 14
    assert shifted[0].due.weekday() == original[0].due.weekday()
