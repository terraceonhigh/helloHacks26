"""Shared HTTP fetch settings for adapters that don't go through hub.site
(no login involved - just being a polite anonymous client).

One User-Agent, one timeout, one place to be polite to whatever we're
fetching from (AGENTS.md rule 5) - rather than each adapter re-declaring
its own slightly-different copy.
"""

import requests

USER_AGENT = "UBCHub-student-project (hackathon; https://github.com/terraceonhigh/helloHacks26)"
TIMEOUT = 10


def get_text(url, **params):
    """GET url with our shared User-Agent/timeout and return the response body."""
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text
