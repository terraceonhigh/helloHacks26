"""Behaviour ported from main's tests/test_bookstore.py (not literal copies -
same scenarios, against lauds.adapters.bookstore's pure functions and its
`_get`, monkeypatched the same way main's tests do so nothing here ever
hits the network - AGENTS.md/BRIEF.md's "be polite to the Bookstore")."""
import json
from pathlib import Path

import pytest
import requests

from lauds.adapters import bookstore
from lauds.models import Textbook

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bookstore"


def _html(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---- sections ----------------------------------------------------------------


def test_parse_terms():
    terms = bookstore.parse_terms(_html("terms.html"))
    assert {"term": "2026W1", "label": "Winter Term 1 - Sept 2026"} in terms


def test_parse_sections():
    sections = bookstore.parse_sections(_html("sections_cpsc.html"))
    keys = {s["key"] for s in sections}
    assert "UBCV,2026W1,CPSC,CPSC121,101" in keys
    match = next(s for s in sections if s["key"] == "UBCV,2026W1,CPSC,CPSC121,101")
    assert match["code"] == "CPSC121"
    assert match["section"] == "101"
    assert "Models Of Computation" in match["title"]


def test_course_from_section_canonicalises_the_bookstores_own_code():
    # "CPSC121" (no space) -> "CPSC 121", the same canonical form every
    # other source's course code collapses onto.
    section = {"key": "k", "code": "CPSC121", "section": "101", "title": "Models Of Computation"}
    course = bookstore.course_from_section(section, "2026W1")
    assert (course.code, course.section, course.term, course.title) == \
        ("CPSC 121", "101", "2026W1", "Models Of Computation")


def test_parse_sections_falls_back_without_crashing_on_a_short_id():
    # A malformed/unexpected `id` (fewer than the usual 5 comma parts) used
    # to raise IndexError in the regex-miss fallback; it degrades instead.
    html = (
        '<div id="course_form"><ul><li class="course" id="weird-id">'
        '<label for="x">Not the usual format</label></li></ul></div>'
    )
    assert bookstore.parse_sections(html) == \
        [{"key": "weird-id", "code": "weird-id", "section": "", "title": "Not the usual format"}]


def test_list_sections_calls_get_with_right_params(monkeypatch):
    seen = {}

    def fake_get(url, **params):
        seen["url"], seen["params"] = url, params
        return _html("sections_cpsc.html")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    html = bookstore._get(f"{bookstore.TEXTBOOK_BASE}/Course/course", campus="UBCV", term="2026W1", program="CPSC")
    assert seen["params"] == {"campus": "UBCV", "term": "2026W1", "program": "CPSC"}
    assert len(bookstore.parse_sections(html)) > 10


# ---- textbooks -----------------------------------------------------------


def test_parse_textbooks_required_book():
    books = bookstore.parse_textbooks(_html("textbooks_cpsc121.html"), "CPSC 121")
    assert len(books) == 1
    book = books[0]
    assert book.isbn == "9781337694193"
    assert book.required is True
    assert book.price == 302.88  # new price preferred over the cheaper digital tier
    assert book.course == "CPSC 121"


def test_parse_textbooks_none_listed_returns_empty_list():
    assert bookstore.parse_textbooks(_html("textbooks_none.html"), "CPSC 100") == []


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
    # "$50" (no ".dd") used to fail the price regex entirely and be
    # silently skipped.
    books = bookstore.parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].price == 50.0  # new price ($50), not the used rental price


def test_parse_textbooks_not_required_is_not_flagged_required():
    # "Not Required" contains the substring "required"; a naive `in` check
    # would wrongly flag this book as required.
    books = bookstore.parse_textbooks(_SYNTHETIC_COURSE_ITEM, "K1")
    assert books[0].required is False


def test_pick_price_prefers_new_then_used_then_digital():
    assert bookstore._pick_price(10.0, 5.0, 2.0) == 10.0
    assert bookstore._pick_price(None, 5.0, 2.0) == 5.0
    assert bookstore._pick_price(None, None, 2.0) == 2.0
    assert bookstore._pick_price(None, None, None) is None


# ---- store links -----------------------------------------------------------


def test_parse_catalog_page_isbn_to_store_link():
    catalog, more = bookstore.parse_catalog_page(_html("products_page1.json"))
    assert more is True
    assert catalog.get("9781337694193") == \
        "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"


def test_parse_catalog_page_empty_page_signals_no_more():
    catalog, more = bookstore.parse_catalog_page(json.dumps({"products": []}))
    assert catalog == {} and more is False


def test_fetch_catalog_stops_after_empty_page(monkeypatch):
    calls = []

    def fake_get(url, **params):
        calls.append(params["page"])
        return json.dumps({"products": []})

    monkeypatch.setattr(bookstore, "_get", fake_get)
    assert bookstore._fetch_catalog() == {}
    assert calls == [1]  # empty page 1 stops the loop, no wasted requests


def test_fetch_catalog_returns_partial_on_network_failure(monkeypatch):
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert bookstore._fetch_catalog() == {}


def test_attach_store_links_leaves_unmatched_isbn_alone():
    catalog, _ = bookstore.parse_catalog_page(_html("products_page1.json"))
    page2, _ = bookstore.parse_catalog_page(_html("products_page2.json"))
    catalog.update(page2)
    books = [
        Textbook(course="CPSC 121", title="Discrete Math", isbn="9781337694193", required=True, price=302.88, url=""),
        Textbook(course="CPSC 121", title="Companion", isbn="0000000000000", required=False, price=None, url=""),
    ]
    linked = bookstore.attach_store_links(books, catalog)
    assert linked[0].url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"
    assert linked[1].url == ""  # not found - left as-is, not crashed on


# ---- fetch(): the public entry point + per-term cache -----------------------


def test_fetch_returns_courses_and_textbooks_with_links(monkeypatch, tmp_path):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))

    def fake_get(url, **params):
        if url.endswith("/Course/course"):
            return _html("sections_cpsc.html")
        if url.endswith("/CourseSearch/"):
            return _html("textbooks_cpsc121.html") if params["course[]"] == "UBCV,2026W1,CPSC,CPSC121,101" \
                else _html("textbooks_none.html")
        if url.endswith("/products.json"):
            pages = [_html("products_page1.json"), _html("products_page2.json")]
            return pages[params["page"] - 1] if params["page"] <= len(pages) else json.dumps({"products": []})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    bundle = bookstore.fetch("CPSC", "2026W1", use_cache=False)
    assert len(bundle.courses) > 10
    assert any(c.code == "CPSC 121" for c in bundle.courses)
    cpsc121_books = [t for t in bundle.textbooks if t.course == "CPSC 121"]
    assert len(cpsc121_books) == 1
    assert cpsc121_books[0].url == "https://bookstore.ubc.ca/products/discrete-mathematics-with-applications-5e"


def test_fetch_degrades_to_empty_on_total_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    monkeypatch.setattr(bookstore, "_get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    bundle = bookstore.fetch("CPSC", "2026W1", use_cache=False)
    assert bundle.courses == [] and bundle.textbooks == []


def test_fetch_reuses_the_per_term_cache_without_a_second_network_round(monkeypatch, tmp_path):
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path))
    calls = []

    def fake_get(url, **params):
        calls.append(url)
        if url.endswith("/Course/course"):
            return _html("sections_cpsc.html")
        if url.endswith("/CourseSearch/"):
            return _html("textbooks_cpsc121.html") if params["course[]"] == "UBCV,2026W1,CPSC,CPSC121,101" \
                else _html("textbooks_none.html")
        return json.dumps({"products": []})

    monkeypatch.setattr(bookstore, "_get", fake_get)
    first = bookstore.fetch("CPSC", "2026W1")
    assert calls  # the first sync really did hit the network
    calls.clear()
    second = bookstore.fetch("CPSC", "2026W1")
    assert calls == []  # the second, same-term sync served entirely from cache
    assert [c.code for c in second.courses] == [c.code for c in first.courses]
