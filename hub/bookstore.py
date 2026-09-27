"""UBC Bookstore adapter: sections, textbooks and store links.

Everything here hits public, logged-out pages (docs/api-standards.md, AGENTS.md
rule 5):
- the.bookstore.ubc.ca: an anonymous course/textbook lookup (PHP "eSolution" site, plain HTML)
- bookstore.ubc.ca: the public Shopify storefront's products.json

Be polite: one request at a time, a real User-Agent (hub.net), and cache per
term (docs/design.md's ttl=86400 caching is a Streamlit-layer concern; this
module just makes each call cheap enough to cache).

Unlike Canvas/Workday/PrairieLearn, the Bookstore doesn't originate its own
course list - it needs to know which courses to look up textbooks for.
fetch(courses) takes courses already known from another source (hub.db.courses(),
canonicalized to "FACULTY NUMBER" + a short term like "2026W1") rather than
logging in anywhere.

Try it:  uv run python -m hub.bookstore
"""

import json
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from hub.logic import normalise_course_code
from hub.models import Textbook
from hub.net import get_text as _get

TEXTBOOK_BASE = "https://the.bookstore.ubc.ca"
STORE_BASE = "https://bookstore.ubc.ca"


# ---------------------------------------------------------------------------
# List sections for one department
# ---------------------------------------------------------------------------


def list_terms(campus="UBCV"):
    """Return [{"term": "2026W1", "label": "Winter Term 1 - Sept 2026"}, ...].

    Returns [] (not an exception) if the Bookstore can't be reached, so a
    site outage degrades the UI to "unavailable" instead of crashing it
    (AGENTS.md: "Handle failure without crashing the dashboard").
    """
    try:
        html = _get(f"{TEXTBOOK_BASE}/Course/term", campus=campus)
    except requests.RequestException:
        return []
    return _parse_terms(html)


def _parse_terms(html):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find(id="term_form")
    out = []
    for a in form.find_all("a") if form else []:
        term = re.search(r"term=([\w]+)", a.get("href", ""))
        if not term:
            continue
        label = a.get_text(strip=True).split(" - ", 1)
        out.append({"term": term.group(1), "label": label[1] if len(label) > 1 else a.get_text(strip=True)})
    return out


def list_sections(program, term, campus="UBCV"):
    """Return [{"key": "UBCV,2026W1,CPSC,CPSC121,101", "code": "CPSC121", "section": "101", "title": "..."}].

    Returns [] (not an exception) on a network failure -- see list_terms.
    """
    try:
        html = _get(f"{TEXTBOOK_BASE}/Course/course", campus=campus, term=term, program=program)
    except requests.RequestException:
        return []
    return _parse_sections(html)


def _parse_sections(html):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find(id="course_form")
    out = []
    for li in (form.find_all("li", class_="course") if form else []):
        key = li.get("id")
        label = li.find("label")
        if not key or not label:
            continue
        text = label.get_text(strip=True)  # "CPSC121 101 - Models Of Computation (CPSC)"
        m = re.match(r"(\S+)\s+(\S+)\s+-\s+(.*?)\s*\([^)]*\)\s*$", text)
        if m:
            code, section, title = m.groups()
        else:
            # Fall back to reading the section key itself. It's scraped HTML,
            # not ours to trust the shape of, so don't assume it has 5 parts.
            parts = key.split(",")
            code, section, title = (parts[3], parts[4], text) if len(parts) >= 5 else (key, "", text)
        out.append({"key": key, "code": code, "section": section, "title": title})
    return out


# ---------------------------------------------------------------------------
# Scrape one section's textbooks
# ---------------------------------------------------------------------------


@dataclass
class _RawTextbook:
    """Bookstore-shaped textbook, before fetch() merges sections and collapses
    the three price tiers into hub.models.Textbook's single `price` (rule 1:
    only fetch()'s return value is the shared model - everything upstream of
    it can stay provider-shaped)."""
    course_key: str
    title: str
    isbn: str
    required: bool
    price_new: float | None
    price_used: float | None
    price_digital: float | None


def fetch_textbooks(course_key):
    """GET the CourseSearch page for one section and parse it into _RawTextbooks.

    Returns [] both when the page says "No course materials are currently
    listed" (a normal, common state, not a failure) and when the Bookstore
    can't be reached at all (a real failure) -- either way the caller just
    sees no textbooks for that section instead of crashing.
    """
    try:
        html = _get(f"{TEXTBOOK_BASE}/CourseSearch/", source="course", **{"course[]": course_key})
    except requests.RequestException:
        return []
    return _parse_textbooks(html, course_key)


# Cents are optional: some listings show a whole-dollar price ("$50") with no
# decimal part at all, and a regex that requires ".dd" would silently skip it.
_PRICE_RE = re.compile(r"\$([\d,]+(?:\.\d{1,2})?)")


def _parse_textbooks(html, course_key):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find(class_="course_search_body")
    if body is None or "No course materials are currently listed" in body.get_text():
        return []

    books = []
    for item in body.find_all("div", class_="course_item", recursive=False):
        title_el = item.find("div", class_="course_item_title")
        status_el = item.find("div", class_="course_item_status")
        isbn_el = item.find("div", class_="course_item_item")
        if title_el is None:
            continue

        title = title_el.get_text(strip=True)
        # startswith, not a plain substring check: a status of "Not Required"
        # or "Not currently required" also contains the word "required".
        required = status_el.get_text(strip=True).lower().startswith("required") if status_el else False
        isbn = isbn_el.get_text(strip=True).split(":", 1)[-1].strip() if isbn_el else ""

        price_new = price_used = price_digital = None
        for option_h3 in item.select(".course_item_buy h3"):
            label = option_h3.get_text(strip=True)
            price_match = _PRICE_RE.search(label)
            if not price_match:
                continue
            price = float(price_match.group(1).replace(",", ""))
            low = label.lower()
            # Check "used"/"new" first: a physical rental tier ("Buy New
            # Rental $50", "Buy Used Rental $35") contains "rental" too, and
            # that used to make it collide with the digital/ebook bucket.
            if "used" in low:
                price_used = price
            elif "new" in low:
                price_new = price
            elif "digital" in low or "ebook" in low or "rental" in low:
                price_digital = price

        books.append(_RawTextbook(
            course_key=course_key, title=title, isbn=isbn, required=required,
            price_new=price_new, price_used=price_used, price_digital=price_digital,
        ))
    return books


# ---------------------------------------------------------------------------
# ISBN -> store link
# ---------------------------------------------------------------------------


def isbn_to_store_link(isbn, max_pages=20, page_size=250):
    """Look up an ISBN in the Shopify storefront and return its product URL, or None.

    Matches against each variant's `sku`, since the Bookstore lists ISBNs there
    (docs/api-standards.md: "GET /products.json?limit=N"; paginate with page=).
    Also returns None (not an exception) if the store can't be reached or
    returns something that isn't valid JSON.

    # ponytail: one paginated store search per textbook, not a cached catalog -
    # fine at a hackathon's course-list scale; fetch products.json once and
    # build an isbn->url map if this ever needs to scale to many textbooks.
    """
    for page in range(1, max_pages + 1):
        try:
            html = _get(f"{STORE_BASE}/products.json", limit=page_size, page=page)
            products = json.loads(html).get("products", [])
        except (requests.RequestException, json.JSONDecodeError):
            return None
        if not products:
            break
        for product in products:
            for variant in product.get("variants", []):
                if variant.get("sku") == isbn:
                    return f"{STORE_BASE}/products/{product['handle']}"
    return None


# ---------------------------------------------------------------------------
# fetch(): the adapter's public entry point
# ---------------------------------------------------------------------------


def _cheapest(raw):
    prices = [p for p in (raw.price_used, raw.price_new, raw.price_digital) if p is not None]
    return min(prices) if prices else None


def fetch(courses, campus="UBCV"):
    """Look up UBC Bookstore textbooks for a list of Course objects (no
    login - public pages only). Returns list[Textbook].

    hub.db doesn't keep a course's section - it's schedule data, not part of
    course identity (hub/db.py's _canonical_code) - so this looks up every
    section under the course's number and merges their textbooks by ISBN.
    The common case (one text for every section) costs nothing extra; a
    required/optional split across sections comes out required (the safer
    default - a student would rather be told about a book they don't need
    than miss one they do).
    """
    sections_by_program = {}  # (campus, term, faculty) -> list_sections(...), fetched once per department
    out = []
    for course in courses:
        faculty, number, _section = normalise_course_code(course.code)
        if not faculty or not number or not course.term:
            continue  # can't build a section key without a parsed code and a term
        cache_key = (campus, course.term, faculty)
        if cache_key not in sections_by_program:
            sections_by_program[cache_key] = list_sections(faculty, course.term, campus=campus)
        matches = [s for s in sections_by_program[cache_key] if s["code"] == f"{faculty}{number}"]

        merged = {}  # isbn -> _RawTextbook, across every matching section
        for section in matches:
            for book in fetch_textbooks(section["key"]):
                existing = merged.get(book.isbn)
                if existing:
                    existing.required = existing.required or book.required
                else:
                    merged[book.isbn] = book

        for book in merged.values():
            out.append(Textbook(
                course=course.code,
                title=book.title,
                isbn=book.isbn,
                required=book.required,
                price=_cheapest(book),
                url=isbn_to_store_link(book.isbn) or "",
            ))
    return out


if __name__ == "__main__":
    from hub import db

    conn = db.connect()
    from hub.models import Course

    known = [Course(code=code, section="", term=term, title=title, grade=grade)
             for code, term, title, grade in db.courses(conn)]
    textbooks = fetch(known)
    db.save(conn, courses=known, textbooks=textbooks)
    for t in textbooks:
        print(f"{t.course:10} {'REQ' if t.required else 'opt'}  {t.title}  "
              f"${t.price if t.price is not None else '?'}  {t.url}")
