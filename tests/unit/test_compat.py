from datetime import date, datetime, time, timedelta, timezone

from lauds.compat import bundle_to_main, to_main
from lauds.models import Bundle, Course, Item, ItemFile, Meeting, Textbook

PDT = timezone(timedelta(hours=-7))


def test_item_projects_to_mains_fields_only_sorted_iso():
    i = Item("CPSC 121", "task", "assignment", "PS1", datetime(2026, 10, 1, 23, 59, tzinfo=PDT), "u", "canvas",
             files=[ItemFile("a.pdf", "u/a")], description="d", points=5.0, extra={"x": 1})
    d = to_main(i)
    assert list(d) == sorted(d)
    assert d == {"category": "task", "course": "CPSC 121", "done": None, "due": "2026-10-01T23:59:00-07:00",
                 "files": [{"kind": "file", "name": "a.pdf", "url": "u/a"}], "kind": "assignment",
                 "source": "canvas", "title": "PS1", "url": "u"}


def test_course_drops_lauds_fields():
    assert to_main(Course("CPSC 121", "101", "2026W1", "M", 84.0, source="workday", url="x")) == \
        {"code": "CPSC 121", "grade": 84.0, "section": "101", "term": "2026W1", "title": "M"}


def test_meeting_times_and_dates_iso():
    m = Meeting("CPSC 121", "lecture", ["MO", "WE"], time(9, 30), time(11), "DMP 110",
                date(2026, 9, 8), date(2026, 12, 4), "workday")
    d = to_main(m)
    assert d["start_time"] == "09:30:00" and d["term_start"] == "2026-09-08" and d["days"] == ["MO", "WE"]


def test_bundle_to_main_keeps_only_present_types():
    t = Textbook("CPSC 121", "Book", "123", True, None, "")
    assert bundle_to_main(Bundle(textbooks=[t]))["textbooks"] == [
        {"course": "CPSC 121", "isbn": "123", "price": None, "required": True, "title": "Book", "url": ""}]
    assert set(bundle_to_main({"items": []})) == {"items"}
