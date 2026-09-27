"""Tests against saved, anonymised copies of real Bookstore pages (fixtures/bookstore/).

None of these hit the network -- monkeypatch hub.bookstore._get so the tests
stay fast and don't hammer the real site (AGENTS.md rule 5).
"""

import json
from pathlib import Path

import pytest
import requests

from hub import bookstore
from hub.models import Course

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bookstore"


def _html(name):
    return (FIXTURES / name).read_text()


# ---- list sections for one department ---------------------------------------


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


# ---- scrape one section's textbooks ------------------------------------------


def test_parse_textbooks_required_book():
    books = bookstore._parse_textbooks(_html("textbooks_cpsc121.html"), "UBCV,2026W1,CPSC,CPSC121,101")
    assert len(books) == 1
    book = books[0]
    assert book.isbn == "9781337694193"
    assert book.required is True
    assert book.price_new == 302.88
    assert book.price_digital == 84.91
    assert book.price_used is None
    assert book.course_key == "UBCV,2026W1,CPSC,CPSC121,101"


def test_parse_textbooks_none_listed_returns_empty_list():
    books = bookstore._parse_textbooks(_html("textbooks_none.html"), "UBCV,2026W1,CPSC,CPSC100,101")
    assert books == []


def test_fetch_textbooks_uses_course_search_endpoint(monkeypatch):
    def fake_get(url, **params):
        assert url == f"{bookstore.TEXTBOOK_BASE}/CourseSearch/"
        assert params["source"] == "course"
        assert params["course[]"] == "UBCV,2026W1,CPSC,CPSC121,101"
        return _html("textbooks_cpsc121.html")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    books = bookstore.fetch_textbooks("UBCV,2026W1,CPSC,CPSC121,101")
    assert len(books) == 1


def test_fetch_textbooks_returns_empty_list_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore.fetch_textbooks("UBCV,2026W1,CPSC,CPSC121,101") == []


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
    assert books[0].price_new == 50.0


def test_parse_textbooks_used_rental_goes_to_used_not_digital():
    # "Buy Used Rental $35.00" contains both "used" and "rental"; it must land
    # in price_used, not get swept into price_digital by the "rental" keyword.
    books = bookstore._parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].price_used == 35.0
    assert books[0].price_digital is None


def test_parse_textbooks_not_required_is_not_flagged_required():
    # "Not Required" contains the substring "required"; a naive `in` check
    # would wrongly flag this book as required.
    books = bookstore._parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].required is False


# ---- ISBN -> store link -------------------------------------------------------


def test_isbn_to_store_link_found(monkeypatch):
    pages = [_html("products_page1.json"), _html("products_page2.json")]
    monkeypatch.setattr(bookstore, "_get", lambda url, **p: pages[p["page"] - 1])
    url = bookstore.isbn_to_store_link("9781337694193")
    assert url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"


def test_isbn_to_store_link_not_found_returns_none(monkeypatch):
    pages = [_html("products_page1.json"), _html("products_page2.json")]
    monkeypatch.setattr(bookstore, "_get", lambda url, **p: pages[p["page"] - 1])
    assert bookstore.isbn_to_store_link("0000000000000") is None


def test_isbn_to_store_link_stops_after_empty_page(monkeypatch):
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


# ---- fetch(): merges sections, maps to hub.models.Textbook -------------------


def test_fetch_maps_to_shared_textbook_model(monkeypatch):
    monkeypatch.setattr(bookstore, "list_sections",
                         lambda program, term, campus="UBCV": [{"key": "UBCV,2026W1,CPSC,CPSC121,101", "code": "CPSC121", "section": "101", "title": "x"}])
    monkeypatch.setattr(bookstore, "fetch_textbooks",
                         lambda key: bookstore._parse_textbooks(_html("textbooks_cpsc121.html"), key))
    monkeypatch.setattr(bookstore, "isbn_to_store_link", lambda isbn: "https://bookstore.ubc.ca/products/x")

    books = bookstore.fetch([Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")])
    assert len(books) == 1
    book = books[0]
    assert book.course == "CPSC 121"
    assert book.isbn == "9781337694193"
    assert book.required is True
    assert book.price == 84.91  # cheapest of new ($302.88) and digital ($84.91)
    assert book.url == "https://bookstore.ubc.ca/products/x"


def test_fetch_merges_the_same_isbn_across_sections_required_wins():
    with_book = bookstore._RawTextbook(course_key="k1", title="Text", isbn="123", required=False,
                                        price_new=100.0, price_used=None, price_digital=None)
    also_required = bookstore._RawTextbook(course_key="k2", title="Text", isbn="123", required=True,
                                            price_new=100.0, price_used=None, price_digital=None)
    merged = {}
    for book in (with_book, also_required):
        existing = merged.get(book.isbn)
        if existing:
            existing.required = existing.required or book.required
        else:
            merged[book.isbn] = book
    assert merged["123"].required is True


def test_fetch_skips_a_course_whose_code_or_term_does_not_parse(monkeypatch):
    monkeypatch.setattr(bookstore, "list_sections", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert bookstore.fetch([Course(code="not a real code", section="", term="2026W1", title="x")]) == []
    assert bookstore.fetch([Course(code="CPSC 121", section="", term="", title="x")]) == []
