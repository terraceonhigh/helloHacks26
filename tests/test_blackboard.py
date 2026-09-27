"""Tests for hub/blackboard.py.

**[unverified]** Every JSON fixture below is constructed from Blackboard's
own public REST API documentation (developer.blackboard.com /
docs.blackboard.com/rest-apis/learn) for the Users, Course Memberships,
Courses and Term resources -- NOT captured from a live instance. No
Blackboard tenant exists anywhere on this project (UBC runs Canvas, plus one
Brightspace course per hub/brightspace.py). See hub/blackboard.py's module
docstring and docs/api-standards.md's Blackboard detail section for exactly
what's a documented fact vs. an unverified hypothesis here. These tests only
confirm the parsers do what this module's own documented-shape assumptions
say they should -- they are not, and cannot be, evidence that a real
Blackboard tenant responds this way.
"""
from hub.blackboard import next_page, to_course

# [unverified] Shape of the Courses resource per Blackboard's docs: the
# human-readable `courseId` (distinct from the internal `id` used in the
# URL), a `name` title, and a `term` object nested in by `?expand=term`.
COURSE_JSON = {
    "id": "_12345_1",
    "courseId": "BIOL101.2026FA",
    "name": "Introduction to Biology",
    "term": {"id": "_9_1", "name": "2026 Fall Term"},
}

# [unverified] Same shape without a `term` (either the tenant doesn't honour
# `expand=term`, or the course simply has none) - must not crash, just leave
# `term` blank, same as hub/brightspace.py's own "no separate field" gap.
COURSE_JSON_NO_TERM = {
    "id": "_67890_1",
    "courseId": "CPSC121.2026FA",
    "name": "Models of Computation",
}

# [unverified] A malformed/edge-case row: no human-readable courseId at all.
COURSE_JSON_NO_COURSE_ID = {
    "id": "_11111_1",
    "name": "Some Course With No Code",
}

# [unverified] Blackboard's documented list-response paging shape.
PAGE_WITH_NEXT = {
    "results": [{"courseId": "1"}],
    "paging": {"nextPage": "/learn/api/public/v1/users/_1_1/courses?offset=1"},
}
PAGE_WITHOUT_NEXT = {"results": [{"courseId": "2"}]}
PAGE_WITH_EMPTY_PAGING = {"results": [{"courseId": "3"}], "paging": {}}


def test_to_course_reads_code_title_and_expanded_term():
    c = to_course(COURSE_JSON)
    assert (c.code, c.title, c.term) == ("BIOL101.2026FA", "Introduction to Biology", "2026 Fall Term")
    assert c.section == ""  # no documented per-membership section field


def test_to_course_leaves_term_blank_when_not_expanded():
    c = to_course(COURSE_JSON_NO_TERM)
    assert c.term == ""
    assert c.code == "CPSC121.2026FA"


def test_to_course_falls_back_to_internal_id_when_no_human_code():
    # ponytail-equivalent: the documented shape isn't guaranteed on every
    # tenant, so a missing courseId must not crash the adapter.
    c = to_course(COURSE_JSON_NO_COURSE_ID)
    assert c.code == "_11111_1"


def test_next_page_returns_documented_paging_field():
    assert next_page(PAGE_WITH_NEXT) == "/learn/api/public/v1/users/_1_1/courses?offset=1"


def test_next_page_none_when_no_paging_object():
    assert next_page(PAGE_WITHOUT_NEXT) is None


def test_next_page_none_when_paging_object_has_no_next_page():
    assert next_page(PAGE_WITH_EMPTY_PAGING) is None
