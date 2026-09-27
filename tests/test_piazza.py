"""Tests for hub/piazza.py.

Every fixture below is SYNTHETIC, built from real field names cited in
hub/piazza.py's module docstring - the piazza-api source
(https://github.com/hfaran/piazza-api) and its own
data_descriptions/Piazza_API_Post_Data_Dictionary.md - NOT captured from a
live Piazza network. [unverified]: nobody on this project has a real Piazza
account to confirm these exact shapes against, same caveat
hub/moodle.py's and hub/brightspace.py's own test files carry. These tests
only check that this adapter's parsing does what it claims with *this*
shaped input, not that Piazza actually sends input shaped exactly like
this.
"""
import json

from hub import piazza, site
from hub.piazza import _history_subject, _int2base, _is_pinned_or_instructor, _nonce, fetch, to_course, to_item

# Real field names per Piazza.get_user_classes (piazza_api/piazza.py:66-89):
# name, term, course_number, id, prof_hash.
NETWORK_WITH_COURSE_NUMBER = {
    "name": "Models of Computation",
    "term": "Fall 2026",
    "course_number": "CPSC 121",
    "id": "hl5qm84dl4t3x2",
    "prof_hash": ["uid_abc"],
}
NETWORK_NO_COURSE_NUMBER = {
    "name": "MATH 200 Discussion",
    "term": "Fall 2026",
    "id": "az9qm84dl4t3x9",
    "prof_hash": [],
}

# Real fields per data_descriptions/Piazza_API_Post_Data_Dictionary.md:
# id, folders, created, type, bucket_name, tags, history (history[0].subject).
PINNED_POST = {
    "id": "kz1abc234d",
    "folders": ["exam"],
    "created": "2026-10-01T12:00:00Z",
    "type": "note",
    "bucket_name": "Pinned",
    "tags": ["pin", "instructor-note", "exam"],
    "history": [{"subject": "Midterm 1 room assignments", "created": "2026-10-01T12:00:00Z", "content": "..."}],
}
INSTRUCTOR_NOTE_NOT_PINNED = {
    "id": "kz1def567g",
    "folders": ["logistics"],
    "created": "2026-10-02T09:00:00Z",
    "type": "note",
    "bucket_name": "Today",
    "tags": ["instructor-note"],
    "history": [{"subject": "Office hours moved this week", "created": "2026-10-02T09:00:00Z", "content": "..."}],
}
ORDINARY_STUDENT_QUESTION = {
    "id": "kz1ghi890j",
    "folders": ["hw1"],
    "created": "2026-10-03T15:00:00Z",
    "type": "question",
    "bucket_name": "Today",
    "tags": ["student", "unanswered"],
    "history": [{"subject": "Question about Q3", "created": "2026-10-03T15:00:00Z", "content": "..."}],
}
# [unverified] capitalised "History" per the data dictionary's own heading.
POST_WITH_CAPITALISED_HISTORY_KEY = {
    "id": "kz1cap999",
    "tags": ["pin"],
    "bucket_name": "Pinned",
    "History": [{"subject": "Final exam date confirmed", "created": "2026-12-01T00:00:00Z"}],
}
POST_WITH_NO_HISTORY = {"id": "kz1nohist", "tags": ["pin"], "bucket_name": "Pinned"}


def test_to_course_reads_course_number_when_present():
    c = to_course(NETWORK_WITH_COURSE_NUMBER)
    assert (c.code, c.title, c.term, c.section) == ("CPSC 121", "Models of Computation", "Fall 2026", "")


def test_to_course_falls_back_to_name_when_course_number_absent():
    # Real per the library: rawc.get('course_number', '') - genuinely absent
    # on some real classes.
    c = to_course(NETWORK_NO_COURSE_NUMBER)
    assert c.code == "MATH 200 Discussion"


def test_is_pinned_or_instructor_true_for_pin_tag():
    assert _is_pinned_or_instructor(PINNED_POST) is True


def test_is_pinned_or_instructor_true_for_instructor_note_tag():
    assert _is_pinned_or_instructor(INSTRUCTOR_NOTE_NOT_PINNED) is True


def test_is_pinned_or_instructor_false_for_ordinary_question():
    assert _is_pinned_or_instructor(ORDINARY_STUDENT_QUESTION) is False


def test_history_subject_reads_first_history_entry():
    assert _history_subject(PINNED_POST) == "Midterm 1 room assignments"


def test_history_subject_falls_back_to_capitalised_history_key():
    assert _history_subject(POST_WITH_CAPITALISED_HISTORY_KEY) == "Final exam date confirmed"


def test_history_subject_empty_when_no_history_at_all():
    assert _history_subject(POST_WITH_NO_HISTORY) == ""


def test_to_item_pinned_post_maps_kind_category_and_never_invents_a_due_date():
    i = to_item(PINNED_POST, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert (i.course, i.category, i.kind, i.title, i.source) == (
        "CPSC 121", "task", "announcement", "Midterm 1 room assignments", "piazza")
    assert i.due is None  # no real due-date field exists anywhere - see module docstring
    assert i.done is None


def test_to_item_url_is_unique_per_post_and_class():
    # The real bug hub/webwork.py's first draft had: two items both getting
    # url="" and colliding under hub/db.py's UNIQUE(source, url). Every
    # post's real, unique `id` must land in the url no matter what.
    a = to_item(PINNED_POST, "CPSC 121", nid="hl5qm84dl4t3x2")
    b = to_item(POST_WITH_CAPITALISED_HISTORY_KEY, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert a.url != b.url
    assert PINNED_POST["id"] in a.url


def test_to_item_none_for_ordinary_non_pinned_post():
    assert to_item(ORDINARY_STUDENT_QUESTION, "CPSC 121", nid="hl5qm84dl4t3x2") is None


def test_to_item_missing_title_falls_back_rather_than_crashing():
    i = to_item(POST_WITH_NO_HISTORY, "CPSC 121", nid="hl5qm84dl4t3x2")
    assert i.title == "(untitled post)"


def test_nonce_is_a_nonempty_base36_string():
    # Real algorithm, cited from piazza_api/nonce.py - just check it
    # produces the right shape, not an exact value (it's time-based).
    n = _nonce()
    assert n and all(c in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in n)


def test_int2base_matches_known_values():
    assert _int2base(0, 36) == "0"
    assert _int2base(35, 36) == "z"
    assert _int2base(36, 36) == "10"


# ---------------------------------------------------------------------------
# Orchestration (_call, _run, fetch): the pure-parsing tests above had zero
# coverage of the actual request/response glue -- exactly where a real bug
# was found on review: one network's feed/post call failing (a malformed
# response, a transient error) propagated out of _run() and wiped out every
# other network's already-parsed courses and items too, the same class of
# bug fixed in hub/google_classroom.py and hub/ed_discussion.py during this
# same review pass.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body, ok=True):
        self._body = body
        self.ok = ok

    def json(self):
        return self._body


def _rpc_result(result):
    return _FakeResponse({"result": result})


def test_fetch_returns_courses_and_items_end_to_end(monkeypatch):
    calls = []

    class FakeReq:
        def post(self, url, data, headers):
            body = json.loads(data)
            method = body["method"]
            calls.append(method)
            if method == "user.status":
                return _rpc_result({"networks": [NETWORK_WITH_COURSE_NUMBER]})
            if method == "network.get_my_feed":
                return _rpc_result({"feed": [{"id": "kz1abc234d"}]})
            if method == "content.get":
                return _rpc_result(PINNED_POST)
            raise AssertionError(f"unexpected method: {method}")

    def fake_fetch_with_session(site_name, base, run):
        assert site_name == "piazza"
        return run(FakeReq())

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)

    courses, items = fetch(limit=5)
    assert [c.code for c in courses] == ["CPSC 121"]
    assert len(items) == 1
    assert items[0].title == "Midterm 1 room assignments"
    assert "user.status" in calls and "network.get_my_feed" in calls and "content.get" in calls


def test_fetch_skips_one_broken_network_but_keeps_the_rest(monkeypatch):
    # The concrete bug fixed on review.
    good_network = NETWORK_WITH_COURSE_NUMBER
    broken_network = NETWORK_NO_COURSE_NUMBER  # its feed call will raise

    class FakeReq:
        def post(self, url, data, headers):
            body = json.loads(data)
            method, params = body["method"], body["params"]
            if method == "user.status":
                return _rpc_result({"networks": [good_network, broken_network]})
            if method == "network.get_my_feed" and params.get("nid") == broken_network["id"]:
                raise RuntimeError("simulated malformed response for this one network")
            if method == "network.get_my_feed":
                return _rpc_result({"feed": [{"id": "kz1abc234d"}]})
            if method == "content.get":
                return _rpc_result(PINNED_POST)
            raise AssertionError(f"unexpected call: {method} {params}")

    def fake_fetch_with_session(site_name, base, run):
        return run(FakeReq())

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)

    courses, items = fetch(limit=5)
    # Both courses still come back (courses are built from user.status alone,
    # before any per-network feed call) -- only the broken network's items
    # are missing, not everything.
    assert {c.code for c in courses} == {"CPSC 121", "MATH 200 Discussion"}
    assert [i.title for i in items] == ["Midterm 1 room assignments"]


def test_fetch_lets_not_logged_in_propagate_for_fetch_with_sessions_own_retry(monkeypatch):
    # NotLoggedIn is the one exception _run() must NOT swallow per-network -
    # hub.site.fetch_with_session catches it at the top level to retry the
    # whole call once after a fresh login (same as every other adapter).
    class FakeReq:
        def post(self, url, data, headers):
            return _FakeResponse({"error": "session expired"})

    seen = []

    def fake_fetch_with_session(site_name, base, run):
        seen.append(1)
        try:
            run(FakeReq())
        except site.NotLoggedIn:
            seen.append("caught")
        return [], []

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)
    fetch()
    assert seen == [1, "caught"]


def test_fetch_returns_empty_on_total_failure(monkeypatch):
    def fake_fetch_with_session(site_name, base, run):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(piazza.site, "fetch_with_session", fake_fetch_with_session)
    assert fetch() == ([], [])
