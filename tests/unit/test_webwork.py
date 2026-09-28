"""Behavioural port of main's tests/test_webwork.py onto lauds.adapters.webwork.
Same fixtures (structurally identical to a real UBC course's WeBWorK page,
webwork.elearning.ubc.ca, checked live 2026-09-26), same assertions -- via
`parse_row`/`to_item` instead of a fetched-and-souped `<li>`."""
from lauds.adapters.webwork import due_from_text, parse_row, to_item
from lauds.models import Item, ItemFile

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


def test_open_set_gets_due_date_and_resolved_link():
    i = parse_row(OPEN_ROW, "MATH 101", base="https://webwork.example.edu/")
    assert (i.category, i.kind, i.title) == ("task", "problemset", "HW1")
    assert i.due.isoformat() == "2026-10-01T23:59:00-07:00"
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW1?effectiveUser=abc123"
    assert i.source == "webwork"


def test_due_is_never_naive():
    i = parse_row(OPEN_ROW, "MATH 101")
    assert i.due.tzinfo is not None


def test_done_is_always_unknown_no_score_signal_on_this_page():
    # WeBWorK's Assignments listing shows no score/grade anywhere; `done`
    # must never be guessed True/False from this page.
    assert parse_row(OPEN_ROW, "MATH 101").done is None
    assert parse_row(PAST_DUE_WITH_DATE_ROW, "MATH 101").done is None


def test_not_open_set_has_no_real_link_but_still_gets_a_stable_synthetic_one():
    # A not-yet-open set with no <a> at all gets a URL synthesised from its
    # own name -- lauds' store upserts items on (source, url), so a blank
    # url would make every unopened set in a course collide.
    i = parse_row(NOT_OPEN_ROW, "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    assert i.title == "HW2"
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW2"
    assert i.due is None


def test_two_not_open_sets_get_different_urls_not_both_blank():
    a = parse_row(NOT_OPEN_ROW, "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    other_row = NOT_OPEN_ROW.replace(">HW2<", ">HW3<")
    b = parse_row(other_row, "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    assert a.url != b.url
    assert a.url and b.url


def test_past_due_set_with_a_review_date_still_has_no_due_date():
    # Once past due, the page's date (if any) is when *answers* unlock, not
    # the original due date -- must not be parsed as `due`.
    i = parse_row(PAST_DUE_WITH_DATE_ROW, "MATH 101", base="https://webwork.example.edu/")
    assert i.title == "HW0"
    assert i.due is None
    assert i.url == "https://webwork.example.edu/webwork2/MATH_101/HW0?effectiveUser=abc123"


def test_past_due_set_with_no_date_at_all_degrades_cleanly():
    i = parse_row(PAST_DUE_NO_DATE_ROW, "MATH 101")
    assert i.title == "Diagnostic"
    assert i.due is None


def test_data_set_type_test_is_a_quiz_not_a_problemset():
    i = parse_row(QUIZ_ROW, "MATH 101")
    assert i.kind == "quiz"
    assert i.category == "deadline"  # category_for("quiz") -> "deadline"


def test_due_from_text_parses_the_real_verified_format():
    dt = due_from_text("Open. Due October 1, 2026, 11:59:00 PM PDT.")
    assert dt.isoformat() == "2026-10-01T23:59:00-07:00"


def test_due_from_text_honours_the_pages_own_abbreviation_not_a_real_tzdata():
    # The page still says "PST" for a 2027 date (BC's permanent-DST change
    # postdates WeBWorK's bundled tzdata) -- must come back as -08:00, not
    # whatever a real America/Vancouver lookup would say for that date.
    dt = due_from_text("Open. Due January 15, 2027, 11:59:00 PM PST.")
    assert dt.isoformat() == "2027-01-15T23:59:00-08:00"


def test_due_from_text_does_not_itself_distinguish_open_date_from_due_date():
    # due_from_text DOES match this text (it's just looking for the date
    # shape) -- gating on data-set-status is to_item's job, not this
    # function's, so it must never be called on a not-open set's text.
    assert due_from_text("Will open on September 30, 2026, 12:01:00 AM PDT.") is not None


def test_due_from_text_none_for_blank_or_no_date():
    assert due_from_text("") is None
    assert due_from_text("Answers available for review.") is None
    assert due_from_text(None) is None


def test_to_item_and_parse_row_agree():
    # to_item (bs4 Tag in) and parse_row (raw text in) must produce the same
    # Item for the same underlying markup -- parse_row is just to_item with
    # its own parsing step.
    from bs4 import BeautifulSoup
    li = BeautifulSoup(OPEN_ROW, "html.parser").find("li")
    assert to_item(li, "MATH 101", base="https://x/") == parse_row(OPEN_ROW, "MATH 101", base="https://x/")


def test_item_is_a_superset_model_field_for_field():
    i = parse_row(OPEN_ROW, "MATH 101", base="https://x/")
    assert isinstance(i, Item)
    assert i.files == []
    assert isinstance(i.files, list) and all(isinstance(f, ItemFile) for f in i.files)
