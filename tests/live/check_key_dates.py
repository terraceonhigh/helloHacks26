"""Live oracle for hub/key_dates.py (PR #37) - OPT-IN, hits the network.

Not collected by `uv run pytest` (filename isn't test_*.py). Run by hand:

    uv run python tests/live/check_key_dates.py

For every KEY_DATES entry it fetches the public UBC Academic Calendar page
the entry links to (fragment stripped; one GET per distinct page, logged
out, nothing else) and checks that the page's "Payments and Due Dates"
table pairs the same term with the same date - "1st instalment" <->
"Term 1 <Month D, YYYY>", "2nd" <-> "Term 2 ...". It also reports whether
the page states a time of day anywhere, since KEY_DATES hard-codes 23:59.

Exit 0 = every date confirmed; 1 = at least one mismatch or fetch failure.
"""
import re
import sys
from pathlib import Path
from urllib.parse import urldefrag

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub.key_dates import KEY_DATES  # noqa: E402

UA = "UBC-Hub key-dates check (helloHacks26 student project; one request per page)"
TERM_FOR = {"1st": "1", "2nd": "2"}
TIME_OF_DAY = re.compile(r"\b\d{1,2}:\d{2}\b|\bmidnight\b|\bnoon\b|\b\d{1,2}\s*[ap]\.?m\b|Pacific Time|\bP[SD]T\b", re.I)


def page_text(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def main():
    pages, failures = {}, 0
    for campus, entries in KEY_DATES.items():
        for e in entries:
            url = urldefrag(e["url"]).url
            if url not in pages:
                try:
                    pages[url] = page_text(url)
                except requests.RequestException as exc:
                    pages[url] = None
                    print(f"FAIL fetch {url}: {exc}")
            text = pages[url]
            if text is None:
                failures += 1
                continue
            date_part, time_part = e["due"].split("T")
            y, m, d = (int(x) for x in date_part.split("-"))
            human = f"{['January','February','March','April','May','June','July','August','September','October','November','December'][m-1]} {d}, {y}"
            ordinal = re.search(r"\b(1st|2nd)\b", e["title"])
            needle = f"Term {TERM_FOR[ordinal.group(1)]} {human}" if ordinal else human
            ok = needle in text
            failures += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {campus} {e['title']!r}: expects {needle!r} on {url}"
                  + ("" if ok else f" - not found (page mentions {human!r}: {human in text})"))
            if not ok:
                continue
            i = text.index(needle)
            near = TIME_OF_DAY.findall(text[max(0, i - 400): i + 400])
            print(f"     time of day near the date: {near or 'none stated'};"
                  f" KEY_DATES uses {time_part[:5]} ({'stated' if near else 'ASSUMED'})")
    for url, text in pages.items():
        if text is not None:
            hits = sorted(set(TIME_OF_DAY.findall(text)))
            print(f"page {url}: time-of-day phrases anywhere on page: {hits or 'none'}")
    print(f"\n{'PASS' if not failures else 'FAIL'}: {failures} problem(s), {len(pages)} page(s) fetched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
