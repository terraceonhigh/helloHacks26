"""Tests against saved, anonymised copies of real Bookstore pages (fixtures/bookstore/).

None of these hit the network -- monkeypatch hub.bookstore._get so the tests
stay fast and don't hammer the real site (AGENTS.md rule 5).
"""

import json
from pathlib import Path

import pytest

from hub import bookstore

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


def test_list_sections_calls_get_with_right_params(monkeypatch):
    seen = {}

    def fake_get(url, **params):
        seen["url"], seen["params"] = url, params
        return _html("sections_cpsc.html")

    monkeypatch.setattr(bookstore, "_get", fake_get)
    sections = bookstore.list_sections("CPSC", "2026W1")
    assert seen["params"] == {"campus": "UBCV", "term": "2026W1", "program": "CPSC"}
    assert len(sections) > 10


# ---- #6: scrape one section's textbooks -------------------------------------


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


def test_isbn_to_store_link_stops_after_empty_page(monkeypatch):
    calls = []

    def fake_get(url, **params):
        calls.append(params["page"])
        return json.dumps({"products": []})

    monkeypatch.setattr(bookstore, "_get", fake_get)
    bookstore.isbn_to_store_link("anything")
    assert calls == [1]  # empty page 1 stops the loop, no wasted requests
