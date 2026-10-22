"""Shared core for any "student logs in themselves, we reuse the session"
adapter (Canvas, PrairieLearn, ...). Login, session storage, pagination and
429 backoff live here once; a per-site file only supplies a base URL and the
functions that map that site's JSON/HTML onto hub.models.
"""
import json
import time
from pathlib import Path

from requests.utils import parse_header_links


class NotLoggedIn(Exception):
    pass


def state_path(site):
    return Path.home() / ".ubc-hub" / f"{site}-state.json"


def login(site, base, headless=False, timeout_ms=300_000):
    """Open a visible browser at `base`; the student signs in; save the session.

    "Logged in" = we're back on `base` past any /login redirect (CWL, Duo,
    whatever the site uses) - true for Canvas and PrairieLearn today, since
    UBC fronts both with the same CWL flow.
    """
    from playwright.sync_api import sync_playwright

    path = state_path(site)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(base)
        page.wait_for_url(lambda u: u.startswith(base) and "/login" not in u, timeout=timeout_ms)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        page.context.storage_state(path=path)
        path.chmod(0o600)
        browser.close()


def next_link(link_header):
    return next((l["url"] for l in parse_header_links(link_header or "") if l.get("rel") == "next"), None)


def get_all(req, url, params, unwrap=json.loads):
    """GET `url`, follow Link-header pagination, retry on 429. `unwrap` turns
    response text into a list, e.g. Canvas's `while(1);[...]` JSON guard."""
    from urllib.parse import urlencode
    url, out = f"{url}?{urlencode(params, doseq=True)}", []
    while url:
        for attempt in range(5):
            r = req.get(url)
            if r.status != 429:
                break
            time.sleep(2**attempt)  # throttled: back off
        if r.status == 401:
            raise NotLoggedIn
        if not r.ok:
            raise RuntimeError(f"{url} -> {r.status}")
        out += unwrap(r.text())
        url = next_link(r.headers.get("link"))
    return out


def fetch_with_session(site, base, run):
    """Ensure a saved session exists, run `run(request_context)`, and log in
    again (once) if the session turns out to be expired."""
    path = state_path(site)
    if not path.exists():
        login(site, base)
    try:
        return _run_with_saved_session(path, run)
    except NotLoggedIn:
        # login() opens its own sync_playwright(); the first one above must
        # already be closed by now (its `with` block has exited), or this
        # nests two sync Playwright instances in one thread and Playwright
        # raises "Sync API inside the asyncio loop" instead of logging in.
        login(site, base)
        return _run_with_saved_session(path, run)


def _run_with_saved_session(path, run):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context(storage_state=path)
            return run(ctx.request)
        finally:
            browser.close()
