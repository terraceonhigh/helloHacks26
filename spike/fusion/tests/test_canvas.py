"""Canvas adapter against SYNTHETIC fixtures (authored from public docs; no live Canvas)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from fusion.adapters import canvas
from tests.canvas_fake import FakeCanvas, pl_quiz1_url

PDT = timezone(timedelta(hours=-7))


@pytest.fixture
def snap():
    s = FakeCanvas()
    return canvas.fetch(s, s.base), s


def by_title(snap, title):
    (item,) = [i for i in snap.items if i.title == title]
    return item


def test_course(snap):
    snap, _ = snap
    (c,) = snap.courses
    assert c.label == "CPSC_121_101_2026W1"
    assert c.title == "CPSC 121 101 Models of Computation"
    assert c.term_hint == "2026 Winter Term 1"
    assert c.url == "http://canvas.example.invalid/courses/4201"


def test_c1_quiz1_links_to_prairielearn(snap):
    snap, _ = snap
    c1 = by_title(snap, "Quiz 1 (PrairieLearn)")
    assert c1.source == "canvas" and c1.source_id == "assignment:51001"
    assert c1.course_source_id == "4201"
    assert c1.kind == "assignment"
    assert c1.due == datetime(2026, 10, 2, 23, 59, 59, tzinfo=PDT)
    assert c1.due.tzinfo is not None
    assert c1.url == "http://canvas.example.invalid/courses/4201/assignments/51001"
    assert c1.links_out == (pl_quiz1_url(),)
    assert c1.done is False
    assert c1.opens is None
    assert "PrairieLearn" in c1.excerpt


def test_c2_tutorial_canvas_only(snap):
    snap, _ = snap
    c2 = by_title(snap, "Tutorial 2 worksheet")
    assert c2.source_id == "assignment:51002"
    assert c2.due == datetime(2026, 10, 1, 12, 0, tzinfo=PDT)
    assert c2.url == "http://canvas.example.invalid/courses/4201/assignments/51002"
    assert c2.links_out == ()          # same-host file link is not a link out
    assert c2.done is False


def test_exactly_two_items_across_two_pages(snap):
    snap, fake = snap
    assert len(snap.items) == 2
    planner_calls = [c for c in fake.calls if c[0] == "/api/v1/planner/items"]
    assert [c[1] for c in planner_calls] == [None, "bookmark:WyIyMDI2LTEwLTAzVDA2OjU5OjU5WiIsNTEwMDFd"]
    # first call carries the date range from the term; the next link is opaque (no params re-sent)
    assert planner_calls[0][2]["start_date"] == "2026-09-01T07:00:00Z"
    assert planner_calls[0][2]["end_date"] == "2026-12-31T08:00:00Z"
    assert planner_calls[1][2] == {}
    assert snap.notes == ()


def test_courses_asks_for_term(snap):
    _, fake = snap
    assert fake.calls[0][0] == "/api/v1/courses"
    assert fake.calls[0][2]["include[]"] == "term"


def test_while1_prefix_is_optional():
    s = FakeCanvas(strip_prefix=True)          # token-auth path: no prefix
    snap = canvas.fetch(s, s.base)
    assert {i.title for i in snap.items} == {"Quiz 1 (PrairieLearn)", "Tutorial 2 worksheet"}


def test_parse_json_strips_prefix():
    assert canvas.parse_json('while(1);[{"a":1}]') == [{"a": 1}]
    assert canvas.parse_json('[{"a":1}]') == [{"a": 1}]


def test_other_plannable_types():
    """Announcements get no due; notes/discussions/pages map to kinds; override marks done."""
    items = [
        {"context_type": "Course", "course_id": 4201, "plannable_id": 7, "plannable_type": "announcement",
         "plannable_date": "2026-09-20T16:00:00Z", "submissions": False, "planner_override": None,
         "plannable": {"id": 7, "title": "Welcome", "message": '<p>See <a href="https://piazza.example.invalid/x">Piazza</a></p>'},
         "html_url": "/courses/4201/discussion_topics/7"},
        {"context_type": "Course", "course_id": 4201, "plannable_id": 8, "plannable_type": "wiki_page",
         "plannable_date": "2026-09-22T16:00:00Z", "submissions": False,
         "planner_override": {"marked_complete": True},
         "plannable": {"id": 8, "title": "Reading week 3", "body": "<p>ch. 2</p>"},
         "html_url": "/courses/4201/pages/reading-week-3"},
        {"plannable_id": 9, "plannable_type": "planner_note", "submissions": False, "planner_override": None,
         "plannable_date": "2026-09-23T16:00:00Z",
         "plannable": {"id": 9, "title": "Buy clicker", "details": "bookstore"},
         "html_url": "/api/v1/planner_notes/9"},
    ]
    s = FakeCanvas(overrides={("/api/v1/planner/items", None):
                              ("while(1);" + json.dumps(items), {"Content-Type": "application/json"})})
    snap = canvas.fetch(s, s.base)
    ann, page, note = snap.items
    assert ann.kind == "announcement" and ann.due is None
    assert ann.links_out == ("https://piazza.example.invalid/x",)
    assert page.kind == "reading" and page.done is True and page.due is not None
    assert note.kind == "note" and note.course_source_id == "user" and note.done is None
    assert any("user" in n for n in snap.notes)
    # no detail fetches needed: every body was already in the planner item
    assert [c[0] for c in s.calls] == ["/api/v1/courses", "/api/v1/planner/items"]


def test_next_link_case_insensitive_and_missing():
    import requests
    r = requests.Response()
    r.headers["link"] = '<http://x/a?page=2>; rel="next", <http://x/a?page=1>; rel="first"'
    assert canvas.next_link(r) == "http://x/a?page=2"
    r2 = requests.Response()
    r2.headers["Link"] = '<http://x/a?page=1>; rel="current"'
    assert canvas.next_link(r2) is None


def test_broken_source_raises():
    s = FakeCanvas(overrides={("/api/v1/courses", None): ("while(1);{\"errors\":[]}", {})})
    with pytest.raises(ValueError):
        canvas.fetch(s, s.base)


def test_every_request_has_a_timeout():
    fake = FakeCanvas()
    seen = []
    orig = fake.get

    def get(url, params=None, headers=None, **kw):
        seen.append(kw.get("timeout"))
        return orig(url, params=params, headers=headers, **kw)
    fake.get = get
    canvas.fetch(fake, fake.base, now=datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert seen and all(t for t in seen)


def test_links_out_skips_unparseable_hosts():
    assert canvas.links_out('<a href="http://[bad/x">x</a> <a href="http://pl.test/q1">q</a>',
                            "http://canvas.test") == ("http://pl.test/q1",)
