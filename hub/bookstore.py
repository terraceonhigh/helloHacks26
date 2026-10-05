"""UBC Bookstore adapter: sections, textbooks and store links (#5, #6, #7).

Everything here hits public, logged-out pages (AGENTS.md rule 5 - "Be polite
to the Bookstore. Only public, logged-out pages."):
- the.bookstore.ubc.ca: an anonymous course/textbook lookup (PHP "eSolution"
  site, plain HTML)
- bookstore.ubc.ca: the public Shopify storefront's products.json

No setup needed from the student: fetch() takes a department + term (e.g.
"CPSC", "2026W1") - the same two things every other adapter's courses already
carry - rather than a Bookstore-specific section key the student would have
to look up themselves.
"""

import dataclasses
import json
import re

import requests
from bs4 import BeautifulSoup

from hub.logic import normalise_course_code
from hub.models import Course, Textbook
from hub.net import get_text as _get

TEXTBOOK_BASE = "https://the.bookstore.ubc.ca"
STORE_BASE = "https://bookstore.ubc.ca"


# ---------------------------------------------------------------------------
# #5: list sections for one department
# ---------------------------------------------------------------------------


def list_terms(campus="UBCV"):
    """Return [{"term": "2026W1", "label": "Winter Term 1 - Sept 2026"}, ...].

    Returns [] (not an exception) if the Bookstore can't be reached, so a
    site outage degrades the UI to "unavailable" instead of crashing it
    (AGENTS.md: "Handle failure without crashing the dashboard")."""
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

    `key` is the Bookstore's own opaque section id, needed as-is for
    fetch_textbooks(); `code`/`section`/`title` are what the shared model
    wants (see _course_from_section below). Returns [] on a network failure,
    same as list_terms."""
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


def _course_from_section(section, term):
    """The Bookstore's own code, e.g. "CPSC121" - collapse to the shared
    model's "CPSC 121" (hub.logic.normalise_course_code, the same canonical
    form hub.db._canonical_code joins Canvas/Workday courses on) so this
    course row lands on the exact same course as every other source's."""
    faculty, number, _ = normalise_course_code(section["code"])
    code = f"{faculty} {number}" if faculty and number else section["code"]
    return Course(code=code, section=section["section"], term=term, title=section["title"])


# ---------------------------------------------------------------------------
# #6: scrape one section's textbooks
# ---------------------------------------------------------------------------


def fetch_textbooks(course_code, course_key):
    """GET the CourseSearch page for one section and parse it into Textbooks,
    tagged with `course_code` (the shared model's course identity - see
    _course_from_section) rather than the Bookstore's own opaque section key.

    Returns [] both when the page says "No course materials are currently
    listed" (a normal, common state, not a failure) and when the Bookstore
    can't be reached at all (a real failure) - either way the UI just shows
    no textbooks for that course instead of crashing."""
    try:
        html = _get(f"{TEXTBOOK_BASE}/CourseSearch/", source="course", **{"course[]": course_key})
    except requests.RequestException:
        return []
    return _parse_textbooks(html, course_code)


# Cents are optional: some listings show a whole-dollar price ("$50") with no
# decimal part at all, and a regex that requires ".dd" would silently skip it.
_PRICE_RE = re.compile(r"\$([\d,]+(?:\.\d{1,2})?)")


def _pick_price(new, used, digital):
    """The shared model has one `price` field, not the Bookstore's three
    tiers - prefer the full new/retail price (the most conservative, always-
    available estimate a student would budget for), then used, then digital,
    rather than dropping the other two tiers on the floor silently."""
    for price in (new, used, digital):
        if price is not None:
            return price
    return None


def _parse_textbooks(html, course_code):
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

        books.append(Textbook(
            course=course_code, title=title, isbn=isbn, required=required,
            price=_pick_price(price_new, price_used, price_digital), url="",
        ))
    return books


# ---------------------------------------------------------------------------
# #7: ISBN -> store link
# ---------------------------------------------------------------------------


def _store_catalog(max_pages=20, page_size=250):
    """isbn (sku) -> product url, built from one paginated scan of Shopify's
    public catalog. A shared scan that every textbook's lookup reads from,
    rather than re-paginating the whole catalog per ISBN (AGENTS.md rule 5:
    "never hammer it in a loop"). Returns whatever it already has on a
    network failure partway through, never raises."""
    catalog = {}
    for page in range(1, max_pages + 1):
        try:
            body = _get(f"{STORE_BASE}/products.json", limit=page_size, page=page)
            products = json.loads(body).get("products", [])
        except (requests.RequestException, json.JSONDecodeError):
            break
        if not products:
            break
        for product in products:
            for variant in product.get("variants", []):
                sku = variant.get("sku")
                if sku:
                    catalog[sku] = f"{STORE_BASE}/products/{product['handle']}"
    return catalog


def isbn_to_store_link(isbn):
    """Single-ISBN convenience over _store_catalog() - for one-off lookups
    and tests. attach_store_links() below is what fetch() actually uses, so a
    course with several textbooks doesn't rescan the catalog once per book."""
    return _store_catalog().get(isbn)


def attach_store_links(textbooks):
    """Fill in .url for every textbook from one shared catalog scan."""
    catalog = _store_catalog()
    return [dataclasses.replace(t, url=catalog.get(t.isbn, t.url)) for t in textbooks]


# ---------------------------------------------------------------------------
# Public entry point - matches every other adapter's fetch() shape
# (hub.canvas.fetch, hub.prairielearn.fetch): one call, shared-model objects
# out, never an exception.
# ---------------------------------------------------------------------------


def fetch(program, term, campus="UBCV"):
    """Every section in `program` this term, with its textbooks and store
    links - (courses, textbooks). A course with no textbooks listed still
    comes back (an empty Bookstore page is a normal state, not a failure);
    a Bookstore outage just means an empty result, never a crash."""
    sections = list_sections(program, term, campus)
    courses = [_course_from_section(s, term) for s in sections]
    textbooks = []
    for section, course in zip(sections, courses):
        textbooks.extend(fetch_textbooks(course.code, section["key"]))
    return courses, attach_store_links(textbooks)
