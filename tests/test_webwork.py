from bs4 import BeautifulSoup

from hub.webwork import due_from_text, to_item

# Anonymised, but structurally identical to a real UBC course's WeBWorK page
# (webwork.elearning.ubc.ca, checked live 2026-09-26): the <li data-set-status
# ="open|not-open|past-due"> markup, the "fw-bold set-id-tooltip" link/span,
# and the three exact status-line phrasings below are all real, verified
# strings from that page -- not a guess at WeBWorK's documented template.
OPEN_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="open"
    data-set-type="default" data-urgency-sort-order="0" data-name-sort-order="4">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/HW1?effectiveUser=abc123">HW1</a></div>
    <div class="font-sm">Open. Due October 1, 2026, 11:59:00 PM PDT.</div>
    <div class="font-sm"></div>
  </div>
  <div class="hardcopy"><a class="hardcopy-link" href="/webwork2/MATH_101/hardcopy?selected_sets=HW1"></a></div>
</li>
"""

NOT_OPEN_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="not-open"
    data-set-type="default" data-urgency-sort-order="2" data-name-sort-order="5">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><span class="set-id-tooltip" data-bs-title="Upcoming material">HW2</span></div>
    <div class="font-sm">Will open on September 30, 2026, 12:01:00 AM PDT.</div>
    <div class="font-sm"></div>
  </div>
</li>
"""

PAST_DUE_WITH_DATE_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="past-due"
    data-set-type="default" data-urgency-sort-order="3" data-name-sort-order="3">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/HW0?effectiveUser=abc123">HW0</a></div>
    <div class="font-sm">Answers available for review on September 28, 2026, 11:59:00 PM PDT.</div>
    <div class="font-sm"></div>
  </div>
  <div class="hardcopy"><a class="hardcopy-link" href="/webwork2/MATH_101/hardcopy?selected_sets=HW0"></a></div>
</li>
"""

PAST_DUE_NO_DATE_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="past-due"
    data-set-type="default" data-urgency-sort-order="4" data-name-sort-order="1">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/Diagnostic?effectiveUser=abc123">Diagnostic</a></div>
    <div class="font-sm">Answers available for review.</div>
    <div class="font-sm"></div>
  </div>
</li>
"""

QUIZ_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="open"
    data-set-type="test" data-urgency-sort-order="0" data-name-sort-order="4">
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/Quiz1?effectiveUser=abc123">Quiz1</a></div>
    <div class="font-sm">Open. Due October 3, 2026, 11:59:00 PM PDT.</div>
  </div>
</li>
"""


def li(html):
    return BeautifulSoup(html, "html.parser").find("li")


def test_open_set_gets_due_date_and_resolved_link():
    i = to_item(li(OPEN_ROW), "MATH 101", base="https://webwork.example.edu/")
    assert (i.category, i.kind, i.title) == ("task", "problemset", "HW1")
    assert i.due.isoformat() == "2026-10-01T23:59:00-07:00"
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW1?effectiveUser=abc123"
    assert i.source == "webwork"


def test_due_is_never_naive():
    i = to_item(li(OPEN_ROW), "MATH 101")
    assert i.due.tzinfo is not None


def test_done_is_always_unknown_no_score_signal_on_this_page():
    # Verified: WeBWorK's Assignments listing shows no score/grade anywhere;
    # `done` must never be guessed True/False from this page.
    assert to_item(li(OPEN_ROW), "MATH 101").done is None
    assert to_item(li(PAST_DUE_WITH_DATE_ROW), "MATH 101").done is None


def test_not_open_set_has_no_real_link_but_still_gets_a_stable_synthetic_one():
    # Verified: a not-yet-open set has no link at all, and its "Will open on
    # ..." date is an open date, never a due date. But hub.db upserts items
    # on (source, url) -- a blank url would make every not-yet-open set in a
    # course collide, so one is synthesised from the set's own name.
    i = to_item(li(NOT_OPEN_ROW), "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    assert i.title == "HW2"
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW2"
    assert i.due is None


def test_two_not_open_sets_get_different_urls_not_both_blank():
    # The concrete failure this guards against: two not-yet-open sets in the
    # same course must not collide on ("webwork", "") in hub.db.
    a = to_item(li(NOT_OPEN_ROW), "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    other_row = NOT_OPEN_ROW.replace(">HW2<", ">HW3<")
    b = to_item(li(other_row), "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    assert a.url != b.url
    assert a.url and b.url  # neither is blank


def test_past_due_set_with_a_review_date_still_has_no_due_date():
    # Verified: once past due, the page's date (if any) is when *answers*
    # unlock, not the original due date -- must not be parsed as `due`.
    i = to_item(li(PAST_DUE_WITH_DATE_ROW), "MATH 101", base="https://webwork.example.edu/")
    assert i.title == "HW0"
    assert i.due is None
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW0?effectiveUser=abc123"


def test_past_due_set_with_no_date_at_all_degrades_cleanly():
    i = to_item(li(PAST_DUE_NO_DATE_ROW), "MATH 101")
    assert i.title == "Diagnostic"
    assert i.due is None


def test_data_set_type_test_is_a_quiz_not_a_problemset():
    i = to_item(li(QUIZ_ROW), "MATH 101")
    assert i.kind == "quiz"
    assert i.category == "deadline"  # category_for("quiz") -> "deadline"


def test_due_from_text_parses_the_real_verified_format():
    dt = due_from_text("Open. Due October 1, 2026, 11:59:00 PM PDT.")
    assert dt.isoformat() == "2026-10-01T23:59:00-07:00"


def test_due_from_text_does_not_itself_distinguish_open_date_from_due_date():
    # due_from_text DOES match this text (it's just looking for the date
    # shape) -- it's to_item's job to gate on data-set-status and only call
    # due_from_text for an "open" set, never a "not-open" one's open-date text.
    assert due_from_text("Will open on September 30, 2026, 12:01:00 AM PDT.") is not None


def test_due_from_text_none_for_blank_or_no_date():
    assert due_from_text("") is None
    assert due_from_text("Answers available for review.") is None
    assert due_from_text(None) is None
