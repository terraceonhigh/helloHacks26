"""Tests for hub/moodle.py.

Every fixture below is SYNTHETIC - built from Moodle's own published external
API docs (docs/api-standards.md's Moodle section), not captured from a live
site. [unverified]: nobody on this project has a real Moodle account to
confirm these field shapes against, unlike hub/prairielearn.py's fixtures
(captured from a real UBC course). These tests only check that this
adapter's parsing does what it claims to do with *this* shaped input, not
that Moodle actually sends input shaped exactly like this.
"""
from datetime import timezone

from hub.moodle import extract_sesskey, to_course, to_item

# Synthetic: a Moodle page's embedded JS config object, as documented in
# Moodle's theming/JS docs (M.cfg.sesskey). Trimmed to the one field we use.
DASHBOARD_PAGE_WITH_SESSKEY = """
<html><head><script>
var M = {}; M.yui = {}; M.cfg = {"wwwroot":"https:\\/\\/moodle.example.edu","sesskey":"AbCd1234ef","theme":"boost"};
</script></head><body>...</body></html>
"""
DASHBOARD_PAGE_LOGGED_OUT = "<html><body>Please log in</body></html>"

# Synthetic: shaped after core_enrol_get_users_courses's documented return
# (docs.moodle.org/dev/Web_service_API_functions -> core_enrol_get_users_courses).
SYNTHETIC_COURSE = {
    "id": 42,
    "shortname": "CPSC101",
    "fullname": "Intro to Systematic Program Design",
    "idnumber": "",
    "visible": 1,
}

# Synthetic: shaped after core_calendar_get_action_events_by_timesort's
# documented return - each event embeds its own course sub-object.
SYNTHETIC_ASSIGN_EVENT = {
    "id": 9001,
    "name": "Assignment 3: Recursion",
    "modulename": "assign",
    "timesort": 1798761599,  # 2026-12-31 23:59:59 UTC-ish, arbitrary fixed epoch
    "url": "https://moodle.example.edu/mod/assign/view.php?id=555",
    "course": {"id": 42, "shortname": "CPSC101", "fullname": "Intro to Systematic Program Design"},
}
SYNTHETIC_QUIZ_EVENT_NO_URL = {
    "id": 9002,
    "name": "Quiz 2",
    "modulename": "quiz",
    "timesort": 1798000000,
    "url": "",
    "course": {"id": 42, "shortname": "CPSC101", "fullname": "Intro to Systematic Program Design"},
}
SYNTHETIC_EVENT_UNKNOWN_MODULE_NO_DUE = {
    "id": 9003,
    "name": "Some Forum Post",
    "modulename": "forum",
    "timesort": None,
    "url": None,
    "course": {"id": 43, "shortname": "MATH200", "fullname": "Calculus III"},
}


def test_extract_sesskey_finds_it_in_the_js_config():
    assert extract_sesskey(DASHBOARD_PAGE_WITH_SESSKEY) == "AbCd1234ef"


def test_extract_sesskey_none_when_not_logged_in():
    assert extract_sesskey(DASHBOARD_PAGE_LOGGED_OUT) is None


def test_to_course_maps_shortname_and_fullname_grade_always_none():
    c = to_course(SYNTHETIC_COURSE)
    assert (c.code, c.title, c.grade) == ("CPSC101", "Intro to Systematic Program Design", None)


def test_to_item_assignment_event_maps_kind_course_due_and_url():
    i = to_item(SYNTHETIC_ASSIGN_EVENT)
    assert (i.course, i.category, i.kind, i.title, i.source) == (
        "CPSC101", "task", "assignment", "Assignment 3: Recursion", "moodle")
    assert i.url == "https://moodle.example.edu/mod/assign/view.php?id=555"
    assert i.due.tzinfo is not None  # never naive - crashes UI comparisons (hub/models.py)
    assert i.due.astimezone(timezone.utc).timestamp() == 1798761599


def test_to_item_quiz_event_maps_kind_deadline():
    i = to_item(SYNTHETIC_QUIZ_EVENT_NO_URL)
    assert (i.category, i.kind) == ("deadline", "quiz")


def test_to_item_falls_back_to_event_id_url_never_a_repeated_empty_string():
    # hub/webwork.py's first draft gave two different items the same url=""
    # and one silently overwrote the other in hub.db (UNIQUE(source, url)).
    # Every event has a distinct id, so the fallback url is always distinct too.
    i1 = to_item(SYNTHETIC_QUIZ_EVENT_NO_URL)
    i2 = to_item(SYNTHETIC_EVENT_UNKNOWN_MODULE_NO_DUE)
    assert i1.url != "" and i2.url != ""
    assert i1.url != i2.url


def test_to_item_unlisted_modulename_defaults_to_assignment_task():
    i = to_item(SYNTHETIC_EVENT_UNKNOWN_MODULE_NO_DUE)
    assert (i.category, i.kind) == ("task", "assignment")
    assert i.due is None
    assert i.course == "MATH200"
