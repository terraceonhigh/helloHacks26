"""Tests against a fake fixture syllabus - the LLM call is always stubbed
(monkeypatch hub.syllabus._call_llm), so these never touch the network or a
real API key (AGENTS.md rule 8)."""

from pathlib import Path

from hub import syllabus

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "syllabus_cpsc999.txt").read_text()

# Shape _call_llm returns: what a real structured-output response would give
# for fixtures/syllabus_cpsc999.txt, hand-written rather than actually calling
# the API for a fixture.
RAW_ITEMS = [
    {"title": "Assignment 1 (Warm-up)", "kind": "assignment", "due": "2026-09-30T23:59:00",
     "evidence": "Assignment 1 (Warm-up) is due September 30, 2026, 11:59pm."},
    {"title": "Midterm exam", "kind": "exam", "due": "2026-10-22T09:00:00",
     "evidence": "The midterm exam is on October 22, 2026 at 9:00am, in person."},
    {"title": "First reading response", "kind": "reading", "due": None,
     "evidence": "the first one is expected by Week 5 Friday, exact date to be confirmed on the course Piazza."},
    {"title": "PA2", "kind": "assignment", "due": "2026-11-03",
     "evidence": 'your PrairieLearn account will also show "PA2" due November 3, 2026'},
]


def test_fetch_maps_raw_items_to_the_shared_item_model(monkeypatch):
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: RAW_ITEMS)
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    assert len(items) == 4
    assert all(i.course == "CPSC 999" and i.source == "syllabus" for i in items)
    assert [i.title for i in items] == ["Assignment 1 (Warm-up)", "Midterm exam", "First reading response", "PA2"]
    assert [i.kind for i in items] == ["assignment", "exam", "reading", "assignment"]
    assert [i.category for i in items] == ["task", "deadline", "material", "task"]


def test_a_datetime_with_no_timezone_is_assumed_vancouver(monkeypatch):
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: RAW_ITEMS)
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    assignment1 = items[0]
    assert assignment1.due.isoformat() == "2026-09-30T23:59:00-07:00"


def test_a_date_only_due_string_also_gets_a_timezone(monkeypatch):
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: RAW_ITEMS)
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    pa2 = items[3]
    assert pa2.due.isoformat() == "2026-11-03T00:00:00-07:00"


def test_an_unresolved_relative_date_comes_back_with_no_due_date_not_dropped(monkeypatch):
    # The syllabus buries "PA2" (a PrairieLearn deadline) and can't resolve
    # "Week 5 Friday" to a real date - #17: never fail on partial data, an
    # item without a real date still shows up, just unsorted.
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: RAW_ITEMS)
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    reading = items[2]
    assert reading.due is None
    assert reading.title == "First reading response"


def test_each_item_gets_a_distinct_synthetic_identity_url(monkeypatch):
    # No real link exists for a syllabus item, unlike every other adapter -
    # (source, url) is still the identity (rule 4), so two items in the same
    # course must not collide the way an empty "" url would.
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: RAW_ITEMS)
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    urls = {i.url for i in items}
    assert len(urls) == 4
    assert all(u.startswith("syllabus:CPSC 999#") for u in urls)


def test_an_item_with_no_title_is_skipped_not_crashed_on(monkeypatch):
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: [
        {"title": "", "kind": "assignment", "due": None, "evidence": "..."},
        {"title": "Real item", "kind": "assignment", "due": None, "evidence": "..."},
    ])
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    assert [i.title for i in items] == ["Real item"]


def test_an_unrecognized_kind_falls_back_to_assignment_not_a_crash(monkeypatch):
    monkeypatch.setattr(syllabus, "_call_llm", lambda text: [
        {"title": "Something odd", "kind": "", "due": None, "evidence": "..."},
    ])
    items = syllabus.fetch(FIXTURE, "CPSC 999")
    assert items[0].kind == "assignment"
    assert items[0].category == "task"
