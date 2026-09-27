from datetime import date, datetime, timedelta, timezone

from hub.models import Course, Item, Textbook
from hub.view import badge, course_summary, filter_by_course, flag, group_by_day, mask_secret, sort_items

TZ = timezone(timedelta(hours=-7))  # America/Vancouver in September (no DST library needed here)


def _item(title, due, course_key=None, source="canvas"):
    return Item(id=title, course_key=course_key, kind="assignment", title=title, due=due, url=None, source=source)


def test_sort_items_orders_by_due_date_and_puts_no_due_date_last():
    a = _item("first", datetime(2026, 10, 1, tzinfo=TZ))
    b = _item("second", datetime(2026, 10, 3, tzinfo=TZ))
    c = _item("no due date", None)
    result = sort_items([b, c, a])
    assert [i.title for i in result] == ["first", "second", "no due date"]


def test_flag_overdue():
    yesterday = _item("late", datetime.combine(date.today() - timedelta(days=1), datetime.min.time(), TZ))
    assert flag(yesterday) == "overdue"


def test_flag_soon_within_48h():
    tomorrow = _item("soon", datetime.combine(date.today() + timedelta(days=1), datetime.min.time(), TZ))
    assert flag(tomorrow) == "soon"


def test_flag_none_for_far_future():
    later = _item("later", datetime.combine(date.today() + timedelta(days=10), datetime.min.time(), TZ))
    assert flag(later) is None


def test_flag_none_when_no_due_date():
    assert flag(_item("whenever", None)) is None


def test_group_by_day_buckets_and_orders():
    d1 = datetime(2026, 10, 1, 9, tzinfo=TZ)
    d1b = datetime(2026, 10, 1, 17, tzinfo=TZ)
    d2 = datetime(2026, 10, 2, 9, tzinfo=TZ)
    items = [_item("c", d2), _item("a", d1), _item("b", d1b), _item("undated", None)]
    groups = group_by_day(items)
    assert [g[0] for g in groups] == [date(2026, 10, 1), date(2026, 10, 2), None]
    assert [i.title for i in groups[0][1]] == ["a", "b"]
    assert [i.title for i in groups[-1][1]] == ["undated"]


def test_course_summary_totals_required_textbooks_only():
    course = Course(key="K1", code="CPSC 121", section="101", term="2026W1", title="Models of Computation")
    books = [
        Textbook(course_key="K1", title="Required book", isbn="1", required=True, price_new=100.0),
        Textbook(course_key="K1", title="Optional book", isbn="2", required=False, price_new=50.0),
        Textbook(course_key="OTHER", title="Different course", isbn="3", required=True, price_new=999.0),
    ]
    summary = course_summary(course, books)
    assert [t.title for t in summary["required_textbooks"]] == ["Required book"]
    assert summary["required_total"] == 100.0


def test_course_summary_no_required_textbooks_gives_none_total():
    course = Course(key="K2", code="ENGL 110", section="005", term="2026W1", title="Lit")
    assert course_summary(course, [])["required_total"] is None


def test_filter_by_course_keeps_matching_and_drops_unpicked():
    course_code_by_key = {"K1": "CPSC 121", "K2": "MATH 100"}
    a = _item("a", None, course_key="K1")
    b = _item("b", None, course_key="K2")
    assert [i.title for i in filter_by_course([a, b], course_code_by_key, ["CPSC 121"])] == ["a"]


def test_filter_by_course_never_hides_items_with_no_course_key():
    course_code_by_key = {"K1": "CPSC 121"}
    no_course = _item("no course", None, course_key=None)
    result = filter_by_course([no_course], course_code_by_key, [])  # nothing picked at all
    assert result == [no_course]


def test_filter_by_course_never_hides_an_unmapped_course_key():
    # e.g. a raw, not-yet-normalised .ics course tag ("CPSC 121 101") that
    # doesn't match any Course.key ("UBCV,2026W1,CPSC,CPSC121,101") -- this
    # must not silently vanish from every course filter.
    course_code_by_key = {"UBCV,2026W1,CPSC,CPSC121,101": "CPSC 121"}
    unmapped = _item("raw tag item", None, course_key="CPSC 121 101")
    result = filter_by_course([unmapped], course_code_by_key, ["CPSC 121"])
    assert result == [unmapped]


def test_badge_known_and_unknown_sources():
    assert badge("canvas") == "Canvas"
    assert badge("mystery") == "mystery"


def test_mask_secret_short_value_fully_masked():
    assert mask_secret("abcd") == "****"


def test_mask_secret_long_value_shows_only_ends():
    assert mask_secret("1234567890abcdef") == "1234...ef"


def test_mask_secret_empty():
    assert mask_secret("") == ""
