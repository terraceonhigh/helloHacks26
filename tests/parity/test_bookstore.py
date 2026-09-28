"""Parity-to-superset for the bookstore adapter: every golden under
tests/oracle/bookstore/, run through lauds.adapters.bookstore's pure
functions and checked against main's oracle output. Dispatch is on each
golden's own `oracle_call` string, so a new golden that names one of the
same functions is picked up automatically.

Every bookstore case in tests/oracle/ was harvested with a fixed term
("2026W1") that isn't spelled out in any of these `oracle_call` strings
(unlike workday's, which literally says term='2026W1') - it's this repo's
one fixed test term throughout (see every other adapter's goldens), so it's
hardcoded here rather than guessed per golden.
"""
import json

import pytest

from lauds.adapters import bookstore
from lauds.models import Bundle, Textbook
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

GOLDENS = golden_paths("bookstore")
TERM = "2026W1"


def _run_sections(golden, inputs):
    rel = golden["inputs"][0]
    sections = bookstore.parse_sections(inputs[rel])
    courses = [bookstore.course_from_section(s, TERM) for s in sections]
    return Bundle(courses=courses)


def _run_textbooks(golden, inputs):
    rel = golden["inputs"][0]
    oracle_books = golden["output"].get("textbooks", [])
    # The course code is an argument to _parse_textbooks, not something it
    # discovers from the page - when the golden's own expected output is
    # non-empty it already tells us what code the harvester passed; an empty
    # expected list means it never mattered.
    course_code = oracle_books[0]["course"] if oracle_books else "UNUSED"
    books = bookstore.parse_textbooks(inputs[rel], course_code)
    return Bundle(textbooks=books)


def _run_attach_store_links(golden, inputs):
    rel_input = golden["inputs"][0]  # attach_store_links_input.json
    spec = json.loads(inputs[rel_input])
    catalog = {}
    for rel in spec["catalog_pages"]:
        page_catalog, _more = bookstore.parse_catalog_page(inputs[rel])
        catalog.update(page_catalog)
    # attach_store_links only ever changes `.url` - every other field of the
    # pre-call Textbook is exactly what the golden's own expected output
    # already records (this fixture's own input JSON records only `isbn`,
    # see tests/fixtures/bookstore/attach_store_links_input.json).
    by_isbn = {t["isbn"]: t for t in golden["output"]["textbooks"]}
    textbooks = [
        Textbook(course=by_isbn[t["isbn"]]["course"], title=by_isbn[t["isbn"]]["title"], isbn=t["isbn"],
                 required=by_isbn[t["isbn"]]["required"], price=by_isbn[t["isbn"]]["price"], url="")
        for t in spec["textbooks"]
    ]
    return Bundle(textbooks=bookstore.attach_store_links(textbooks, catalog))


def _run(golden, inputs):
    call = golden.get("oracle_call", "")
    if "attach_store_links" in call:
        return _run_attach_store_links(golden, inputs)
    if "_parse_sections" in call:
        return _run_sections(golden, inputs)
    if "_parse_textbooks" in call:
        return _run_textbooks(golden, inputs)
    raise NotImplementedError(f"don't know how to run oracle_call {call!r}")


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_parity(path):
    golden = load_golden(path)
    assert_superset(golden, _run(golden, load_inputs(golden)))
