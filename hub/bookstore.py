"""UBC Bookstore adapter: sections, textbooks and store links.

Everything here hits public, logged-out pages (docs/design.md §7, AGENTS.md rule 5):
- the.bookstore.ubc.ca: an anonymous course/textbook lookup (PHP "eSolution" site, plain HTML)
- bookstore.ubc.ca: the public Shopify storefront's products.json

Be polite: one request at a time, a real User-Agent, and cache per term
(docs/design.md's ttl=86400 caching is a Streamlit-layer concern; this module
just makes each call cheap enough to cache).
"""

import json
import re

import requests
from bs4 import BeautifulSoup

from hub.models import Textbook
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
# #6: scrape one section's textbooks
# ---------------------------------------------------------------------------


def fetch_textbooks(course_key):
    """GET the CourseSearch page for one section and parse it into Textbooks.

    Returns [] both when the page says "No course materials are currently
    listed" (a normal, common state, not a failure) and when the Bookstore
    can't be reached at all (a real failure) -- either way the UI just shows
    no textbooks for that course instead of crashing.
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

        books.append(
            Textbook(
                course_key=course_key,
                title=title,
                isbn=isbn,
                required=required,
                price_new=price_new,
                price_used=price_used,
                price_digital=price_digital,
                store_url=None,
            )
        )
    return books


# ---------------------------------------------------------------------------
# #7: ISBN -> store link
# ---------------------------------------------------------------------------


def isbn_to_store_link(isbn, max_pages=20, page_size=250):
    """Look up an ISBN in the Shopify storefront and return its product URL, or None.

    Matches against each variant's `sku`, since the Bookstore lists ISBNs there
    (docs/api-standards.md: "GET /products.json?limit=N"; paginate with page=).
    Also returns None (not an exception) if the store can't be reached or
    returns something that isn't valid JSON.
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
