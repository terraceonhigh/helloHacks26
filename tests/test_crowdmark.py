"""Tests for hub/crowdmark.py.

There's no live Crowdmark account to test parsing against (see the module
docstring), so there's no fixture-driven parser test here the way
tests/test_prairielearn.py has one -- only the one real function this file
contains: `_origin`'s multi-tenant URL normalisation (mirrors
tests/test_brightspace.py's own test of the same idea), plus a check that
`login()`/`fetch()` do what the module docstring says they do.
"""
from hub.crowdmark import SITE, _origin, fetch, login


def test_origin_passes_through_a_bare_origin_unchanged():
    assert _origin("https://app.crowdmark.com") == "https://app.crowdmark.com"


def test_origin_strips_a_full_sign_in_url_down_to_just_the_origin():
    # https://app.crowdmark.com/sign-in/ubc is the real, live UBC sign-in URL
    # cited in the module docstring -- concatenating a future API path onto
    # it directly (without normalising first) would build a broken URL, same
    # risk hub/brightspace.py's _origin already guards against.
    assert _origin("https://app.crowdmark.com/sign-in/ubc") == "https://app.crowdmark.com"


def test_login_opens_the_normalised_origin(monkeypatch):
    calls = []
    monkeypatch.setattr("hub.crowdmark.site.login", lambda site_name, base: calls.append((site_name, base)))
    login("https://app.crowdmark.com/sign-in/ubc")
    assert calls == [(SITE, "https://app.crowdmark.com")]


def test_fetch_is_an_honest_stub_with_no_network_call():
    # See the module docstring: there's no citable JSON shape for "My
    # Courses" to fetch, so this deliberately returns ([], []) rather than
    # guess at an endpoint or scrape HTML (AGENTS.md rule 6).
    assert fetch("https://app.crowdmark.com/sign-in/ubc") == ([], [])
