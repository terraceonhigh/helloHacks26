"""Piazza adapter: Q&A/discussion board, not primarily a due-date tracker.

Port of main's `hub/piazza.py`. See that file's module docstring for the
full, cited case for reusing `hub.site`'s browser-session login over
piazza-api's raw email+password POST: piazza.com owns its own account
system, a UBC network may or may not sit an SSO front end on it, and the
browser-session path works either way while never letting our own code see
a password. **This port drops `login_with_credentials` entirely** (BRIEF.md
task: "we never handle passwords") - main's fallback direct-POST path for a
network confirmed to have no SSO. The browser-session path
(`lauds.session.login`) is the only path here.

**[UNVERIFIED END-TO-END]**: Piazza has no public API and nothing
self-hostable (unlike Canvas/PrairieLearn/WeBWorK) - there is no live
server to check this against, on humboldt or anywhere. Every mapping below
is cited from the same real source main's docstring cites (the
`piazza-api` client, commit `39681fe`), re-verified against main's own
fixtures. **Grade: fixture-only** - see BRIEF.md's per-adapter grading
rule; this can only ever move off fixture-only if someone reaches a real
Piazza account.

Try it:  uv run lauds sync piazza
"""
import json
from random import random as _random
from string import ascii_letters as _ascii_letters
from string import digits as _digits
from time import time as _time

from lauds import session
from lauds.models import Bundle, Course, Item, category_for

NAME = "piazza"
DESCRIPTION = "Piazza (pinned/instructor posts only - Piazza has no due-date field)"

BASE = "https://piazza.com"
# Real, cited from piazza_api/rpc.py:30-33 (PiazzaRPC.__init__.base_api_urls).
LOGIC_API = f"{BASE}/logic/api"
MAIN_API = f"{BASE}/main/api"

# How many feed posts per class to follow up on with a full content.get call.
# The feed never carries enough fields to skip the second call (see
# hub/piazza.py's "only gives you an id" section) - capped to stay polite
# about repeated per-post calls.
DEFAULT_POST_LIMIT = 40

_EXRADIX_DIGITS = _digits + _ascii_letters


def _int2base(x, base):
    """Real algorithm, cited verbatim (renamed private) from
    piazza_api/nonce.py's `_int2base` - reproduced rather than depending on
    the `piazza-api` package, since only this one documented shape is used."""
    if x == 0:
        return _EXRADIX_DIGITS[0]
    sign = 1 if x > 0 else -1
    x *= sign
    digits = []
    while x:
        digits.append(_EXRADIX_DIGITS[int(x % base)])
        x = int(x / base)
    if sign < 0:
        digits.append("-")
    digits.reverse()
    return "".join(digits)


def _nonce():
    """Real algorithm, cited from piazza_api/nonce.py's `nonce()`: a base-36
    encoding of the current time in milliseconds, plus a base-36 random
    tail. Piazza's real `logic/api` endpoint takes this as an `aid` query
    parameter on every call (rpc.py:556-562)."""
    return f"{_int2base(int(_time() * 1000), 36)}{_int2base(round(_random() * 1679616), 36)}"


def login(**opts):
    """Open a visible browser at piazza.com; the student signs in (Piazza's
    own login form, or their institution's SSO if that network has it
    enabled); save only the session."""
    session.login(NAME, BASE, **opts)


def to_course(network: dict) -> Course:
    """One raw class dict from `user.status`'s real `networks` list -> a
    Course. Real field names, cited from `Piazza.get_user_classes`
    (piazza_api/piazza.py:66-89): `name`, `term`, `course_number` (often
    absent - real source uses `.get(..., '')`), `id`. Piazza has no native
    "section" concept the way Canvas/Workday do, so section is always blank.
    # ponytail: `course_number` is genuinely absent on some real classes -
    # falls back to `name` so a course still gets a usable code rather than
    # an empty one.
    """
    return Course(
        code=network.get("course_number") or network.get("name", ""),
        section="",
        term=network.get("term", ""),
        title=network.get("name", ""),
        source=NAME,
    )


def _history_subject(post: dict) -> str:
    """A post's original subject line: real per the data dictionary,
    top-level `subject`/`content` don't exist - the first `history` entry
    (or the doc's own capitalised `History`, casing `[unverified]`) carries
    it as innerHTML. Returns "" if genuinely absent rather than guessing."""
    history = post.get("history") or post.get("History") or []
    return (history[0].get("subject", "") or "") if history else ""


def _is_pinned_or_instructor(post: dict) -> bool:
    """Real "worth surfacing" signal, per the data dictionary's `tags`
    field: `"pin"` for a pinned post, `"instructor-note"` for one an
    instructor wrote; `bucket_name == "Pinned"` is the same real signal the
    web UI itself buckets pinned posts under, checked as a fallback."""
    tags = post.get("tags") or []
    return "pin" in tags or "instructor-note" in tags or post.get("bucket_name") == "Pinned"


def to_item(post: dict, course_code: str, nid: str = "") -> Item | None:
    """One full post dict (a real `content.get` response) -> an `Item`, or
    `None` if it isn't pinned/instructor content - nothing else here is
    worth surfacing without a due date. `due` is always `None`: nothing
    date-shaped exists anywhere in scope for Piazza (class dict, feed
    entry, full post, history entry) - surfaced honestly, never a
    fabricated date (see hub/piazza.py's "Items: no real due-date field
    exists at all"). `url` follows Piazza's ordinary web-UI post link shape,
    `<BASE>/class/<nid>?cid=<post id>` - `[reasoned]`, not from the
    piazza-api source (an API client, not a web app); `id` is real and
    unique per post, so `url` can't collide across posts or classes even if
    the exact shape is wrong.
    """
    if not _is_pinned_or_instructor(post):
        return None
    kind = "announcement"
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=_history_subject(post) or "(untitled post)",
        due=None,
        url=f"{BASE}/class/{nid}?cid={post.get('id', '')}",
        source=NAME,
        done=None,  # no completion/read signal in scope here
    )


def parse_capture(capture: dict) -> Bundle:
    """Experimental browser-extension capture (already filtered to
    pinned/instructor posts by `extension/providers/piazza.js`) -> a
    Bundle. Same validation as main's `hub.piazza.parse_capture`: reject
    anything not shaped like a real Piazza capture rather than guess."""
    if not isinstance(capture, dict) or capture.get("source") != NAME:
        raise ValueError("expected Piazza capture")
    networks = capture.get("networks")
    if (not isinstance(networks, list) or len(networks) > 100
            or any(not isinstance(row, dict) for row in networks)):
        raise ValueError("invalid Piazza capture")
    courses, items = [], []
    for network in networks:
        nid = network.get("id")
        posts = network.get("posts", [])
        if (not isinstance(nid, str) or not nid.isalnum()
                or not isinstance(posts, list) or len(posts) > DEFAULT_POST_LIMIT
                or any(not isinstance(post, dict) for post in posts)):
            raise ValueError("invalid Piazza network")
        course = to_course(network)
        courses.append(course)
        for post in posts:
            if not isinstance(post.get("id"), str) or not post["id"].isalnum():
                raise ValueError("invalid Piazza post")
            item = to_item(post, course.code, nid)
            if item is not None:
                items.append(item)
    return Bundle(courses=courses, items=items)


def _call(req, method, data=None, nid=None, nid_key="nid", api_type="logic"):
    """Real generic RPC shape, cited from `PiazzaRPC.request`
    (piazza_api/rpc.py:525-572): POST a `{"method", "params"}` JSON body to
    `logic/api` (with a `?method=&aid=<nonce>` query string) or `main/api`.
    `req` is `lauds.session`'s request object (Playwright's request context
    in production; a fake in tests).

    Failure detection: `[reasoned]`, not confirmed - real piazza-api only
    ever guards client-side on whether a cookie exists before sending a
    request. Conservatively, a non-OK HTTP status or a JSON body with a
    real `error` field (the one documented failure shape) is treated as
    "not logged in" and lets `session.fetch_with_session` retry the login
    once - harmless even if the real cause was something else, since
    that's a no-op retry either way.
    """
    endpoint = LOGIC_API if api_type == "logic" else MAIN_API
    if api_type == "logic":
        endpoint = f"{endpoint}?method={method}&aid={_nonce()}"
    body = json.dumps({"method": method, "params": dict({nid_key: nid}, **(data or {}))})
    r = req.post(endpoint, data=body, headers={"Content-Type": "application/json"})
    if not r.ok:
        raise session.NotLoggedIn
    result = r.json()
    if result.get("error"):
        raise session.NotLoggedIn
    return result.get("result")


def _posts_for_network(req, nid, course_code, limit):
    """Real feed -> full-post-per-id -> Items. Real params for
    `get_my_feed` (rpc.py:388-412): `limit`, `offset`, `sort` (only
    documented value `"updated"`)."""
    feed = _call(req, "network.get_my_feed", nid=nid, data={"limit": limit, "offset": 0, "sort": "updated"})
    cids = [p.get("id") for p in (feed or {}).get("feed", []) if p.get("id")][:limit]
    items = []
    for cid in cids:
        # Real params, cited from `PiazzaRPC.content_get` (rpc.py:126-142).
        post = _call(req, "content.get", nid=nid, data={"cid": cid, "student_view": None})
        item = to_item(post or {}, course_code, nid) if post else None
        if item is not None:
            items.append(item)
    return items


def _run(req, limit):
    # Real params for user.status: none beyond the implicit nid=None
    # (piazza_api/piazza.py:56-64, rpc.py:517-523).
    status = _call(req, "user.status", nid=None) or {}
    networks = status.get("networks", [])
    courses = [to_course(n) for n in networks]
    items = []
    for n in networks:
        code = to_course(n).code
        nid = n.get("id")
        if not nid:
            continue
        try:
            items += _posts_for_network(req, nid, code, limit)
        except session.NotLoggedIn:
            raise  # a genuine session expiry: let fetch_with_session retry the whole run
        except Exception:
            # One network's feed/post call failing (malformed response,
            # transient error) must not drop every other network's courses
            # and items along with it.
            continue
    return Bundle(courses=courses, items=items)


def fetch(limit=DEFAULT_POST_LIMIT, **opts) -> Bundle:
    """Return a Bundle for the student's own Piazza classes. Logs in (opens
    a browser window) if there's no saved session.

    Does NOT swallow every failure into an empty Bundle any more (BRIEF
    major finding): that blanket `except Exception` hid a genuine
    `NotLoggedIn` (an expired/no session) as a silent, successful, empty
    sync - `lauds status` would say "ok" with 0 items instead of "stale,
    re-login needed", exactly the failure mode BRIEF's "never silently
    partial" rule is about. `_run`'s own per-network try/except already
    isolates one broken class's feed from the rest (see above); `sync_one`
    isolates one broken adapter from the rest of `sync` - piazza needs no
    extra safety net on top of either."""
    return session.fetch_with_session(NAME, BASE, lambda req: _run(req, limit))


if __name__ == "__main__":
    print(fetch())
