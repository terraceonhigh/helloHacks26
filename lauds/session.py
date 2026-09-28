"""Shared core for any "student logs in themselves, we reuse the session"
adapter. Port of main's hub/site.py.

Login happens in a real, visible browser; we keep only Playwright's
storage_state (cookies), saved 0600 under ~/.config/lauds/ - never a
password. Pagination (Link header), 429 backoff and "session expired"
detection live here once; an adapter supplies a base URL and pure parse
functions.

Every function that talks HTTP takes a request object `req` with
`req.get(url) -> response`, where a response has `.status`, `.ok`,
`.headers` (dict, lower-case keys) and `.text()`. Playwright's
APIRequestContext fits as-is; `RequestsContext` wraps a requests.Session to
the same shape; tests pass a fake.
"""
import json
import time
from urllib.parse import urlencode

from requests.utils import parse_header_links

from lauds import paths


class NotLoggedIn(Exception):
    pass


def state_path(site):
    return paths.state_path(site)


def _default_logged_in(base):
    return lambda u: u.startswith(base) and "/login" not in u


def login(site, base, headless=False, timeout_ms=300_000, logged_in=None):
    """Open a visible browser at `base`; the student signs in; save the session.

    "Logged in" defaults to: back on `base`, past any /login redirect (CWL,
    Duo, ...). An adapter whose site differs passes `logged_in(url) -> bool`.
    """
    from playwright.sync_api import sync_playwright

    path = state_path(site)
    paths.ensure_dir(path.parent)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.goto(base)
            page.wait_for_url(logged_in or _default_logged_in(base), timeout=timeout_ms)
            page.context.storage_state(path=str(path))
            paths.secure_file(path)
        finally:
            browser.close()
    return path


def next_link(link_header):
    return next((l["url"] for l in parse_header_links(link_header or "") if l.get("rel") == "next"), None)


def _header(r, name):
    h = getattr(r, "headers", None) or {}
    if callable(h):  # some clients expose headers() as a method
        h = h()
    return h.get(name) or h.get(name.title()) or h.get(name.lower())


def get(req, url, params=None, retries=5, sleep=time.sleep):
    """One GET with 429 backoff (1, 2, 4, 8 s...). 401 -> NotLoggedIn,
    any other non-ok -> RuntimeError. Returns the response."""
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urlencode(params, doseq=True)}"
    for attempt in range(retries):
        r = req.get(url)
        if r.status != 429:
            break
        if attempt < retries - 1:
            sleep(2**attempt)  # throttled: back off
    if r.status == 401:
        raise NotLoggedIn(url)
    if not r.ok:
        raise RuntimeError(f"{url} -> {r.status}")
    return r


def get_all(req, url, params=None, unwrap=json.loads, sleep=time.sleep, max_pages=1000):
    """GET `url`, follow Link-header pagination, retry on 429. `unwrap` turns
    response text into a list (e.g. strip Canvas's `while(1);` guard)."""
    out, pages = [], 0
    url = f"{url}?{urlencode(params or {}, doseq=True)}" if params else url
    while url:
        r = get(req, url, sleep=sleep)
        out += unwrap(r.text())
        url = next_link(_header(r, "link"))
        pages += 1
        if pages >= max_pages:  # a server that links to itself must not hang us
            raise RuntimeError(f"pagination did not end after {max_pages} pages")
    return out


def fetch_with_session(site, base, run, logged_in=None, _playwright=None):
    """Ensure a saved session exists, run `run(request_context)`, and log in
    again (once) if the session turns out to be expired."""
    if _playwright is None:
        from playwright.sync_api import sync_playwright as _playwright

    path = state_path(site)
    if not path.exists():
        login(site, base, logged_in=logged_in)
    with _playwright() as pw:
        browser = pw.chromium.launch()
        try:
            try:
                return run(browser.new_context(storage_state=str(path)).request)
            except NotLoggedIn:
                browser.close()
                login(site, base, logged_in=logged_in)
                browser = pw.chromium.launch()
                return run(browser.new_context(storage_state=str(path)).request)
        finally:
            browser.close()


class _Resp:
    def __init__(self, r):
        self.status = r.status_code
        self.ok = r.ok
        self.headers = {k.lower(): v for k, v in r.headers.items()}
        self._r = r

    def text(self):
        return self._r.text

    def body(self):
        return self._r.content


class RequestsContext:
    """requests.Session -> the `req.get(url)` shape above, for token/API-key
    adapters that don't need a browser session. Always has a timeout."""

    def __init__(self, session=None, headers=None, timeout=30):
        import requests

        self.session = session or requests.Session()
        if headers:
            self.session.headers.update(headers)
        self.timeout = timeout

    def get(self, url):
        return _Resp(self.session.get(url, timeout=self.timeout))
