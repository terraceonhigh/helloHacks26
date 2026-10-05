"""hub/demo.py: the fake demo student's whole term, through the real adapters + fusion."""
import socket
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from hub import demo

# Fixed "now" so the test doesn't depend on today (the UBC key dates are real
# calendar dates; fixture offsets move with `now`). A Sunday, 11:00 Vancouver.
NOW = datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc)
TODAY = NOW.astimezone(demo.VAN).date()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("hub.demo must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(requests.Session, "request", refuse)
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


@pytest.fixture
def out():
    return demo.demo_rows(NOW)


@pytest.fixture
def raw():
    return demo._gather(NOW)


def van_date(row):
    return datetime.fromisoformat(row["due"]).astimezone(demo.VAN).date()


def test_rows_come_from_every_provider(out, raw):
    assert out["demo"] is True
    assert {"canvas", "prairielearn", "webwork", "ubc_key_dates"} <= {r["source"] for r in out["items"]}
    assert {"canvas", "piazza"} <= {r["source"] for r in out["announcements"]}
    courses, items, meetings, textbooks = raw
    assert {i.source for i in items} == {"canvas", "prairielearn", "webwork", "piazza", "ubc_key_dates"}
    assert "MATH_V 100A ALL SECTIONS 2026W1" in {c.code for c in courses}  # Brightspace
    assert {m.source for m in meetings} == {"workday"}
    assert textbooks


def test_every_due_is_tz_aware_or_none(out, raw):
    for i in raw[1]:
        assert i.due is None or i.due.tzinfo is not None, i
    for r in out["items"] + out["announcements"]:
        if r["due"] is not None:
            assert datetime.fromisoformat(r["due"]).tzinfo is not None, r


def test_now_is_week_5_of_a_15_week_term(raw):
    _, items, meetings, _ = raw
    week1 = demo.term_week1(NOW)
    assert week1.weekday() == 0
    assert (TODAY - week1).days // 7 + 1 == demo.NOW_WEEK == 5
    lectures = [m for m in meetings if m.kind == "lecture"]
    assert {(m.term_end - m.term_start).days // 7 + 1 for m in lectures} == {13}  # 13 teaching weeks
    term_start = min(m.term_start for m in meetings)
    dated = [i.due for i in items if i.due and i.source != "ubc_key_dates"]
    span_weeks = (max(dated).astimezone(demo.VAN).date() - term_start).days / 7
    assert 14 <= span_weeks <= 15.5  # classes plus a ~2-week exam period
    assert min(dated).astimezone(demo.VAN).date() < TODAY - timedelta(weeks=3)  # weeks 1-4 are past


def test_every_task_mode_and_kind_appears(out, raw):
    _, items, meetings, textbooks = raw
    assert {"assignment", "problemset", "quiz", "exam", "event", "announcement", "payment"} <= {i.kind for i in items}
    assert {"assignment", "problemset", "quiz", "exam", "event", "payment"} <= {r["kind"] for r in out["items"]}
    assert {r["category"] for r in out["items"]} == {"task", "deadline"}
    assert {m.kind for m in meetings} == {"lecture", "lab", "tutorial", "seminar", "exam"}
    assert {t.required for t in textbooks} == {True, False}
    titles = " | ".join(i.title for i in items)
    for mode in ("Problem Set", "WeBWorK", "Quiz", "Lab ", "Reading:", "Discussion post",
                 "Final project milestone", "Midterm", "Final Exam", "Essay"):
        assert mode in titles, mode
    assert any(i.due is None and i.kind == "assignment" for i in items)  # undated tasks exist upstream


def test_cross_source_duplicates_collapse(out, raw):
    items = raw[1]
    # The raw adapters really do see these twice...
    assert {i.source for i in items if i.title == "Quiz 3: Recursion"} == {"canvas", "prairielearn"}
    assert {i.source for i in items if i.title == "WeBWorK 5"} == {"canvas", "webwork"}
    assert sum(i.title == "Problem Set 4" for i in items) == 2  # Canvas API + calendar feed
    assert sum(i.title == "Essay 1 draft" for i in items) == 2
    # ...and the fused rows once each; WeBWorK's own copy wins over its Canvas mirror.
    for title in ("Quiz 3: Recursion", "WeBWorK 5", "Problem Set 4", "Essay 1 draft", "MATH 100 Midterm 1"):
        assert sum(r["title"] == title for r in out["items"]) == 1, title
    assert next(r for r in out["items"] if r["title"] == "WeBWorK 5")["source"] == "webwork"


def test_source_url_identity_is_unique(out):
    rows = out["items"] + out["announcements"]
    keys = [(r["source"], r["url"]) for r in rows]
    assert len(keys) == len(set(keys))
    assert all(r["url"] for r in rows)
    assert not any("ubc.ca" in r["url"] for r in rows if r["source"] != "ubc_key_dates")


def test_course_codes_unify_across_sources(out, raw):
    courses, items, _, _ = raw
    spellings = {c.code for c in courses} | {i.course for i in items}
    assert {"CPSC_V 110-101 2026W1", "CPSC_V 110-L1A 2026W1", "CPSC 110",
            "MATH_V 100A ALL SECTIONS 2026W1", "MATH 100"} <= spellings
    codes = {c["code"] for c in out["courses"]}
    assert codes == {"CPSC 110", "MATH 100", "PHYS 117", "ENGL 110", "PSYC 102", "UBCV"}
    assert {r["course"] for r in out["items"] + out["announcements"]} <= codes
    assert {m["course"] for m in out["schedule"]} <= codes
    by_source = Counter(r["source"] for r in out["items"] if r["course"] == "CPSC 110")
    assert {"canvas", "prairielearn"} <= set(by_source)


def test_courses_are_fused_across_providers(out):
    by_code = {c["code"]: c for c in out["courses"]}
    assert by_code["CPSC 110"]["grade"] == 86.4  # the lab shell's unknown grade doesn't clobber it
    assert by_code["CPSC 110"]["title"] == "Intro to Program Design (Demo)"
    assert by_code["MATH 100"]["title"] == "Differential Calculus (Demo)"  # not Brightspace's long name
    assert all(c["term"] == "2026W1" for c in out["courses"])


def test_overdue_and_urgency_flags(out):
    overdue = [r for r in out["items"] if r["status"] == "overdue"]
    assert len(overdue) == 5
    assert all(r["urgency"] == "overdue" for r in overdue)
    assert [r["status"] for r in out["items"][:len(overdue)]] == ["overdue"] * len(overdue)
    assert {r["source"] for r in overdue} == {"canvas", "prairielearn"}
    assert "HW 3: Compound data" in {r["title"] for r in overdue}  # PL: 100% tier over, 50% tier open
    assert {"soon", "upcoming"} <= {r["status"] for r in out["items"]}
    assert {"medium", "low"} <= {r["urgency"] for r in out["items"]}


def test_done_items_are_hidden(out):
    titles = {r["title"] for r in out["items"]}
    for done in ("HW 4: Lists",  # 100% on PrairieLearn
                 "Quiz 2: Functions",  # credit schedule over, 85% on PrairieLearn
                 "Problem Set 1", "Lab 1",  # submitted on Canvas
                 "Reading: Demo Story Anthology, ch. 1",  # ticked off in Canvas's planner
                 "Tuition: 1st instalment due (Winter Session)"):  # a key date that has passed
        assert done not in titles, done


def test_several_items_due_the_same_day(out):
    tomorrow = [r["title"] for r in out["items"] if van_date(r) == TODAY + timedelta(days=1)]
    assert len(tomorrow) >= 5, tomorrow
    midterms = [r for r in out["items"] if "Midterm 1" in r["title"] and r["kind"] in ("event", "exam")]
    assert len({van_date(r) for r in midterms}) >= 3  # a heavy midterm week


def test_2359_vancouver_is_the_next_day_in_utc(out):
    row = next(r for r in out["items"] if r["title"] == "Problem Set 4")
    due = datetime.fromisoformat(row["due"])
    assert (due.astimezone(demo.VAN).hour, due.astimezone(demo.VAN).minute) == (23, 59)
    assert due.astimezone(timezone.utc).date() == van_date(row) + timedelta(days=1)


def test_dates_are_relative_to_now():
    # Problem Set 4 is stored as "{{due:+1d@23:59}}": tomorrow, 23:59 Vancouver
    # time, whenever the request happens (a wall-clock check, since DST moves
    # the UTC offset between the two dates).
    for now in (NOW, NOW.replace(month=11), NOW.replace(year=2027, month=3)):
        row = next(r for r in demo.demo_rows(now)["items"] if r["title"] == "Problem Set 4")
        due = datetime.fromisoformat(row["due"]).astimezone(demo.VAN)
        assert (due.date() - now.astimezone(demo.VAN).date()).days == 1
        assert (due.hour, due.minute) == (23, 59)


def test_the_same_overdue_count_on_any_weekday():
    for days in range(7):
        rows = demo.demo_rows(NOW + timedelta(days=days))["items"]
        assert sum(r["status"] == "overdue" for r in rows) == 5


def test_demo_rows_is_deterministic(out):
    assert demo.demo_rows(NOW) == out


def test_schedule_is_this_terms_meetings(out):
    schedule = out["schedule"]
    assert len(schedule) == 9
    classes = [m for m in schedule if m["kind"] != "exam"]
    assert all(m["term_start"] <= TODAY.isoformat() <= m["term_end"] for m in classes)
    exam = next(m for m in schedule if m["kind"] == "exam")
    assert date.fromisoformat(exam["term_start"]) > TODAY + timedelta(weeks=8)  # in the exam period
    assert {d for m in schedule for d in m["days"]} == {"MO", "TU", "WE", "TH", "FR"}
    cpsc_lab = next(m for m in schedule if m["course"] == "CPSC 110" and m["kind"] == "lab")
    assert (cpsc_lab["days"], cpsc_lab["start_time"], cpsc_lab["end_time"]) == (["MO"], "14:00", "16:00")


def test_announcements_are_undated_and_only_pinned_piazza_posts(out):
    assert all(r["due"] is None and r["kind"] == "announcement" for r in out["announcements"])
    piazza = {r["title"] for r in out["announcements"] if r["source"] == "piazza"}
    assert piazza == {"Problem Set 4 clarification: helper functions are allowed", "Midterm 1 formula sheet posted"}


def test_textbooks_are_only_the_students_own_sections(out):
    assert {t["course"] for t in out["textbooks"]} == {"CPSC 110", "PHYS 117"}  # ENGL 110 lists none
    assert all(t["isbn"].startswith("978000") for t in out["textbooks"])  # fake ISBNs
    required = next(t for t in out["textbooks"] if t["required"] and t["course"] == "CPSC 110")
    assert required["price"] == 89.95  # new price preferred over used
