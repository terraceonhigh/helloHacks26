"""UBC Bookstore adapter: sections, textbooks and store links - public,
logged-out pages only (BRIEF.md: "polite"; no student session, ever):

- the.bookstore.ubc.ca: an anonymous course/textbook lookup (plain HTML).
- bookstore.ubc.ca: the public Shopify storefront's products.json.

Clean port of main's hub/bookstore.py, split so every page-shape decision is
a pure function over already-fetched text (parity tests replay the
committed fixtures through these) and `fetch()` does only the HTTP + a
per-term disk cache, so re-running `lauds sync bookstore` twice in a row
doesn't re-scrape the whole department and the storefront catalog every
time (BRIEF.md: "per-term cache").
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import replace

import requests
from bs4 import BeautifulSoup

from lauds import paths
from lauds.models import Bundle, Course, Textbook, normalise_course_code

NAME = "bookstore"
DESCRIPTION = "UBC Bookstore: sections, textbooks and store links (public pages)"

TEXTBOOK_BASE = "https://the.bookstore.ubc.ca"
STORE_BASE = "https://bookstore.ubc.ca"
USER_AGENT = "lauds-student-project (https://github.com/terraceonhigh/lauds-cli)"
TIMEOUT = 10
CACHE_TTL = 6 * 3600  # ponytail: fixed 6h TTL, no per-call override - upgrade if a shorter/longer window is ever wanted


def _get(url, **params):
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


# --- sections: list_sections page -------------------------------------------


def parse_terms(html: str) -> list[dict]:
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


def parse_sections(html: str) -> list[dict]:
    """[{"key": "UBCV,2026W1,CPSC,CPSC121,101", "code": "CPSC121", "section":
    "101", "title": "..."}, ...] - `key` is the Bookstore's own opaque
    section id, needed as-is for fetch_textbooks(); the rest is what the
    shared model wants (see course_from_section)."""
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
            # Fall back to the section key itself - it's scraped HTML, not
            # ours to trust the shape of, so don't assume it has 5 parts.
            parts = key.split(",")
            code, section, title = (parts[3], parts[4], text) if len(parts) >= 5 else (key, "", text)
        out.append({"key": key, "code": code, "section": section, "title": title})
    return out


def course_from_section(section: dict, term: str) -> Course:
    """The Bookstore's own code (e.g. "CPSC121") collapsed to the shared
    model's "CPSC 121", so a Bookstore-only course lands on the same row as
    every other source's (lauds.models.canonical_code)."""
    faculty, number, _ = normalise_course_code(section["code"])
    code = f"{faculty} {number}" if faculty and number else section["code"]
    return Course(code=code, section=section["section"], term=term, title=section["title"], source=NAME)


# --- textbooks: one section's CourseSearch page ------------------------------

# Cents are optional: some listings show a whole-dollar price ("$50") with no
# decimal part, and a regex requiring ".dd" would silently skip it.
_PRICE_RE = re.compile(r"\$([\d,]+(?:\.\d{1,2})?)")


def _pick_price(new, used, digital):
    """One `price` field, not the Bookstore's three tiers: prefer the full
    new/retail price (the most conservative always-available estimate),
    then used, then digital - never drop the other tiers on the floor
    silently by picking whichever parses first."""
    for price in (new, used, digital):
        if price is not None:
            return price
    return None


def parse_textbooks(html: str, course_code: str) -> list[Textbook]:
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
        # startswith, not a plain substring check: "Not Required" also
        # contains the word "required".
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
            # Rental $50") also contains "rental" and would otherwise
            # collide with the digital/ebook bucket.
            if "used" in low:
                price_used = price
            elif "new" in low:
                price_new = price
            elif "digital" in low or "ebook" in low or "rental" in low:
                price_digital = price

        books.append(Textbook(course=course_code, title=title, isbn=isbn, required=required,
                               price=_pick_price(price_new, price_used, price_digital), url=""))
    return books


# --- store links: paginated Shopify catalog ----------------------------------


def parse_catalog_page(body: str) -> tuple[dict[str, str], bool]:
    """One products.json page's raw body -> ({isbn (sku): product url}, more)
    - `more` is whether the page had any products at all (an empty page ends
    pagination even if every product on an earlier, non-empty page happened
    to lack a sku - the two are different signals)."""
    products = json.loads(body).get("products", [])
    catalog = {}
    for product in products:
        for variant in product.get("variants", []):
            sku = variant.get("sku")
            if sku:
                catalog[sku] = f"{STORE_BASE}/products/{product['handle']}"
    return catalog, bool(products)


def attach_store_links(textbooks: list[Textbook], catalog: dict[str, str]) -> list[Textbook]:
    """Fill in `.url` for every textbook from an already-built catalog scan -
    pure, so it takes a catalog rather than fetching one itself; fetch()
    below builds that catalog with one shared paginated scan per sync,
    never one scan per book."""
    return [replace(t, url=catalog.get(t.isbn, t.url)) for t in textbooks]


def _fetch_catalog(max_pages=20, page_size=250) -> dict[str, str]:
    """The paginated network scan attach_store_links() needs a catalog for -
    one shared scan per sync, not one re-paginate per book (BRIEF.md: "never
    hammer it in a loop"). Stops at the first empty page. Returns whatever it
    already has on a network failure partway through, never raises - a
    Bookstore outage just means fewer store links, not a crashed sync."""
    catalog = {}
    for page in range(1, max_pages + 1):
        try:
            body = _get(f"{STORE_BASE}/products.json", limit=page_size, page=page)
            page_catalog, more = parse_catalog_page(body)
        except (requests.RequestException, json.JSONDecodeError):
            break
        if not more:
            break
        catalog.update(page_catalog)
    return catalog


# --- per-term disk cache ------------------------------------------------------


def _cache_path(program, term, campus):
    return paths.data_dir() / "cache" / "bookstore" / f"{campus}-{term}-{program}.json"


def _cache_load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - data.get("fetched_at", 0) > CACHE_TTL:
        return None
    return data["bundle"]


def _cache_save(path, bundle_dict):
    paths.ensure_dir(path.parent)
    path.write_text(json.dumps({"fetched_at": time.time(), "bundle": bundle_dict}), encoding="utf-8")
    paths.secure_file(path)


def _bundle_to_cache(courses, textbooks):
    return {
        "courses": [c.__dict__ for c in courses],
        "textbooks": [t.__dict__ for t in textbooks],
    }


def _bundle_from_cache(data):
    return [Course(**c) for c in data["courses"]], [Textbook(**t) for t in data["textbooks"]]


# --- fetch(): the public entry point ------------------------------------------


def fetch(program: str, term: str, campus: str = "UBCV", use_cache: bool = True) -> Bundle:
    """Every section in `program` this term, with its textbooks and store
    links. Reuses a same-day-ish disk cache (BRIEF.md's "per-term cache")
    instead of re-scraping the department + the whole storefront catalog on
    every `lauds sync` - a course with no textbooks listed still comes back
    (an empty page is a normal state, not a failure).

    A genuine network failure - the sections page itself, or any one
    section's textbook page - now raises instead of degrading to an empty
    or partial Bundle (BRIEF major finding): silently caching that partial
    scrape used to serve it back as a healthy result for CACHE_TTL (6h)
    even after the site recovered, and `lauds sync` reported "ok" the whole
    time. `_fetch_catalog()`'s own degrade-to-partial is unchanged and
    deliberate (module docstring): store links are a nice-to-have on top of
    the real course/textbook data this function is actually responsible
    for, not core data."""
    cache_path = _cache_path(program, term, campus)
    if use_cache:
        cached = _cache_load(cache_path)
        if cached is not None:
            courses, textbooks = _bundle_from_cache(cached)
            return Bundle(courses=courses, textbooks=textbooks)

    try:
        sections_html = _get(f"{TEXTBOOK_BASE}/Course/course", campus=campus, term=term, program=program)
        sections = parse_sections(sections_html)
    except requests.RequestException as e:
        raise RuntimeError(f"bookstore: could not load the sections page: {e}") from e

    courses = [course_from_section(s, term) for s in sections]
    textbooks = []
    for section, course in zip(sections, courses):
        try:
            html = _get(f"{TEXTBOOK_BASE}/CourseSearch/", source="course", **{"course[]": section["key"]})
        except requests.RequestException as e:
            raise RuntimeError(f"bookstore: could not load textbooks for {course.code}: {e}") from e
        textbooks.extend(parse_textbooks(html, course.code))
    textbooks = attach_store_links(textbooks, _fetch_catalog())

    if use_cache:
        _cache_save(cache_path, _bundle_to_cache(courses, textbooks))
    return Bundle(courses=courses, textbooks=textbooks)
