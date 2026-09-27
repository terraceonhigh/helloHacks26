"""Tests against saved copies of real (anonymised - no student data was ever
in these pages, they're public course/textbook listings) Bookstore pages
(fixtures/bookstore/).

None of these hit the network -- monkeypatch hub.bookstore._get so the tests
stay fast and don't hammer the real site (AGENTS.md rule 5).
"""

import json
from pathlib import Path

import requests

from hub import bookstore
from hub.models import Textbook

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bookstore"


def _html(name):
    return (FIXTURES / name).read_text()


# ---- #5: list sections for one department ----------------------------------


def test_parse_terms():
    terms = bookstore._parse_terms(_html("terms.html"))
    assert {"term": "2026W1", "label": "Winter Term 1 - Sept 2026"} in terms


def test_parse_sections():
    sections = bookstore._parse_sections(_html("sections_cpsc.html"))
    keys = {s["key"] for s in sections}
    assert "UBCV,2026W1,CPSC,CPSC121,101" in keys
    match = next(s for s in sections if s["key"] == "UBCV,2026W1,CPSC,CPSC121,101")
    assert match["code"] == "CPSC121"
    assert match["section"] == "101"
    assert "Models Of Computation" in match["title"]


def test_course_from_section_canonicalises_the_bookstores_own_code():
    # "CPSC121" (no space) -> "CPSC 121" - the same canonical form
    # hub.db._canonical_code collapses Canvas/Workday course codes onto, so a
    # Bookstore-only course still lands on the same row as any other source.
    section = {"key": "k", "code": "CPSC121", "section": "101", "title": "Models Of Computation"}
    course = bookstore._course_from_section(section, "2026W1")
    assert (course.code, course.section, course.term, course.title) == ("CPSC 121", "101", "2026W1", "Models Of Computation")


def test_list_sections_calls_get_with_right_params(monkeypatch):
    seen = {}

    def fake_get(url, **params):
        seen["url"], seen["params"] = url, params
        return _html("sections_cpsc.html")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    sections = bookstore.list_sections("CPSC", "2026W1")
    assert seen["params"] == {"campus": "UBCV", "term": "2026W1", "program": "CPSC"}
    assert len(sections) > 10


def test_parse_sections_falls_back_without_crashing_on_a_short_id():
    # A malformed/unexpected `id` (fewer than the usual 5 comma parts) used to
    # raise IndexError in the regex-miss fallback; it should degrade instead.
    html = (
        '<div id="course_form"><ul><li class="course" id="weird-id">'
        '<label for="x">Not the usual format</label></li></ul></div>'
    )
    sections = bookstore._parse_sections(html)
    assert sections == [{"key": "weird-id", "code": "weird-id", "section": "", "title": "Not the usual format"}]


def test_list_terms_returns_empty_list_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore.list_terms() == []


def test_list_sections_returns_empty_list_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    assert bookstore.list_sections("CPSC", "2026W1") == []


# ---- #6: scrape one section's textbooks -------------------------------------


def test_parse_textbooks_required_book():
    books = bookstore._parse_textbooks(_html("textbooks_cpsc121.html"), "CPSC 121")
    assert len(books) == 1
    book = books[0]
    assert book.isbn == "9781337694193"
    assert book.required is True
    assert book.price == 302.88  # new price preferred over the cheaper digital tier
    assert book.course == "CPSC 121"


def test_parse_textbooks_none_listed_returns_empty_list():
    books = bookstore._parse_textbooks(_html("textbooks_none.html"), "CPSC 100")
    assert books == []


def test_fetch_textbooks_uses_course_search_endpoint(monkeypatch):
    def fake_get(url, **params):
        assert url == f"{bookstore.TEXTBOOK_BASE}/CourseSearch/"
        assert params["source"] == "course"
        assert params["course[]"] == "UBCV,2026W1,CPSC,CPSC121,101"
        return _html("textbooks_cpsc121.html")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    books = bookstore.fetch_textbooks("CPSC 121", "UBCV,2026W1,CPSC,CPSC121,101")
    assert len(books) == 1
    assert books[0].course == "CPSC 121"


def test_fetch_textbooks_returns_empty_list_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore.fetch_textbooks("CPSC 121", "UBCV,2026W1,CPSC,CPSC121,101") == []


_SYNTHETIC_COURSE_ITEM = """
<div class="course_search_body">
<div class="course_item">
<div class="course_item_header">
<div class="course_item_status"> Not Required
:</div>
<div class="course_item_title">Some Optional Companion Book</div>
</div>
<div class="course_item_data">
<div class="course_item_item"><span>Item#:</span> 1111111111</div>
</div>
<div class="course_item_options"><div class="course_item_buy"><div class="options">
<h3 class="accordion_h3">Buy New $50</h3>
<h3>Buy Used Rental $35.00</h3>
</div></div></div>
</div>
</div>
"""


def test_parse_textbooks_price_without_cents_is_not_dropped():
    # "$50" (no ".dd") used to fail _PRICE_RE entirely and be silently skipped.
    books = bookstore._parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].price == 50.0  # new price ($50), not the used rental price


def test_parse_textbooks_not_required_is_not_flagged_required():
    # "Not Required" contains the substring "required"; a naive `in` check
    # would wrongly flag this book as required.
    books = bookstore._parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].required is False


def test_pick_price_prefers_new_then_used_then_digital():
    assert bookstore._pick_price(10.0, 5.0, 2.0) == 10.0
    assert bookstore._pick_price(None, 5.0, 2.0) == 5.0
    assert bookstore._pick_price(None, None, 2.0) == 2.0
    assert bookstore._pick_price(None, None, None) is None


# A real, live page (UBCV,2026W1,MATH,MATH100,1B2, found while building this
# against the real Bookstore) renders "the instructor hasn't submitted a
# booklist yet" as its own fake course_item - title "No Textbooks Selected",
# item# "NBR", $0 - rather than the page-level "No course materials are
# currently listed" message _parse_textbooks already checks for elsewhere.
_NO_TEXTBOOKS_SELECTED_ITEM = """
<div class="course_search_body">
<div class="course_item">
<div class="course_item_header">
<div class="course_item_status">Required
:</div>
<div class="course_item_title">No Textbooks Selected</div>
</div>
<div class="course_item_data">
<div class="course_item_item"><span>Item#:</span> NBR</div>
</div>
<div class="course_item_options"><div class="course_item_buy"><div class="options">
<h3 class="accordion_h3">Buy New $0.00</h3>
</div></div></div>
</div>
</div>
"""


def test_parse_textbooks_skips_the_bookstores_own_no_textbooks_selected_placeholder():
    assert bookstore._parse_textbooks(_NO_TEXTBOOKS_SELECTED_ITEM, "MATH 100") == []


# ---- #7: ISBN -> store link --------------------------------------------------


def test_isbn_to_store_link_found(monkeypatch):
    pages = [_html("products_page1.json"), _html("products_page2.json")]
    monkeypatch.setattr(bookstore, "_get", lambda url, **p: pages[p["page"] - 1])
    url = bookstore.isbn_to_store_link("9781337694193")
    assert url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"


def test_isbn_to_store_link_not_found_returns_none(monkeypatch):
    pages = [_html("products_page1.json"), _html("products_page2.json")]
    monkeypatch.setattr(bookstore, "_get", lambda url, **p: pages[p["page"] - 1])
    assert bookstore.isbn_to_store_link("0000000000000") is None


def test_store_catalog_stops_after_empty_page(monkeypatch):
    calls = []

    def fake_get(url, **params):
        calls.append(params["page"])
        return json.dumps({"products": []})

    monkeypatch.setattr(bookstore, "_get", fake_get)
    bookstore.isbn_to_store_link("anything")
    assert calls == [1]  # empty page 1 stops the loop, no wasted requests


def test_isbn_to_store_link_returns_none_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore.isbn_to_store_link("9781337694193") is None


def test_isbn_to_store_link_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: "<html>not json</html>")
    assert bookstore.isbn_to_store_link("9781337694193") is None


def test_attach_store_links_scans_the_catalog_once_for_every_book(monkeypatch):
    calls = []

    def fake_get(url, **params):
        calls.append(params["page"])
        pages = [_html("products_page1.json"), _html("products_page2.json")]
        return pages[params["page"] - 1] if params["page"] <= len(pages) else json.dumps({"products": []})

    monkeypatch.setattr(bookstore, "_get", fake_get)
    books = [
        Textbook(course="CPSC 121", title="Discrete Math", isbn="9781337694193", required=True, price=302.88, url=""),
        Textbook(course="CPSC 121", title="Companion", isbn="0000000000000", required=False, price=None, url=""),
    ]
    linked = bookstore.attach_store_links(books)
    assert linked[0].url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"
    assert linked[1].url == ""  # not found - left as-is, not crashed on
    assert calls == [1, 2]  # one catalog scan total, not one per book


# ---- fetch(): the public entry point ----------------------------------------


def test_fetch_returns_courses_and_textbooks_with_links(monkeypatch):
    def fake_get(url, **params):
        if url.endswith("/Course/course"):
            return _html("sections_cpsc.html")
        if url.endswith("/CourseSearch/"):
            return _html("textbooks_cpsc121.html") if params["course[]"] == "UBCV,2026W1,CPSC,CPSC121,101" else _html("textbooks_none.html")
        if url.endswith("/products.json"):
            pages = [_html("products_page1.json"), _html("products_page2.json")]
            return pages[params["page"] - 1] if params["page"] <= len(pages) else json.dumps({"products": []})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    courses, textbooks = bookstore.fetch("CPSC 121", "2026W1")
    # Only CPSC 121's own section(s), never the rest of the CPSC department -
    # see fetch()'s docstring (AGENTS.md rule 5).
    assert courses and all(c.code == "CPSC 121" for c in courses)
    assert len(textbooks) == 1
    assert textbooks[0].course == "CPSC 121"
    assert textbooks[0].url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"


def test_fetch_only_touches_the_one_matching_course_not_the_whole_department(monkeypatch):
    # The real bug this signature exists to prevent: sections_cpsc.html has
    # more than a dozen CPSC sections in it. fetch("CPSC 121", ...) must only
    # ever call the textbook endpoint for CPSC 121's own section(s).
    textbook_calls = []

    def fake_get(url, **params):
        if url.endswith("/Course/course"):
            return _html("sections_cpsc.html")
        if url.endswith("/CourseSearch/"):
            textbook_calls.append(params["course[]"])
            return _html("textbooks_none.html")
        if url.endswith("/products.json"):
            return json.dumps({"products": []})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    bookstore.fetch("CPSC 121", "2026W1")
    # CPSC 121 has 2 sections (101, 102) in this fixture; the department as a
    # whole has 70+ across every CPSC course - only CPSC 121's own may be hit.
    assert textbook_calls == ["UBCV,2026W1,CPSC,CPSC121,101", "UBCV,2026W1,CPSC,CPSC121,102"]


def test_fetch_filters_to_one_section_when_given(monkeypatch):
    def fake_get(url, **params):
        if url.endswith("/Course/course"):
            return _html("sections_cpsc.html")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    # sections_cpsc.html's CPSC 121 only has one real section (101) - ask for
    # a section that doesn't exist and confirm nothing comes back, rather
    # than silently falling back to "every section of this course".
    courses, textbooks = bookstore.fetch("CPSC 121", "2026W1", section="999")
    assert courses == []
    assert textbooks == []


def test_fetch_returns_empty_for_an_unparseable_course_code():
    assert bookstore.fetch("not a course code", "2026W1") == ([], [])


def test_fetch_degrades_to_empty_on_total_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore.fetch("CPSC 121", "2026W1") == ([], [])
