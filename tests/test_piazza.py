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
from hub.piazza import _history_subject, _int2base, _is_pinned_or_instructor, _nonce, to_course, to_item

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
