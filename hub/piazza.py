"""Piazza adapter: Q&A/discussion board, not primarily a due-date tracker.

**[UNVERIFIED END-TO-END]** Nobody on this project has a live Piazza
network, at UBC or anywhere else (docs/api-standards.md already flagged
Piazza as "Fragile" / no official API before this file existed). Every real
claim below was checked by cloning and reading the actual unofficial client
this project's own docs/api-standards.md already pointed at -
https://github.com/hfaran/piazza-api (cloned locally, commit `39681fe`,
"Release 0.16.0") - not paraphrased from memory or a summary. Anything not
traceable to that source is marked `[reasoned]` (a design call we made) or
`[unverified]` (a real gap even the client's own source doesn't resolve).

## What's real, cited from the actual piazza-api source

**Login is a direct POST of email+password - confirmed from the real code,
not the project description.** `PiazzaRPC.user_login` (piazza_api/rpc.py,
lines 55-103 in the cloned source) does exactly this:
1. `GET https://piazza.com/main/csrf_token`, then strips quotes/`;` off the
   response body and splits on `=` to pull out a raw `csrf_token` value
   (rpc.py:65-73 - a genuinely fragile, undocumented scrape of an internal
   endpoint, not a stable public API).
2. `POST https://piazza.com/class` with form data
   `{"from": "/signup", "email": ..., "password": ..., "remember": "on",
   "csrf_token": ...}` (rpc.py:79-88).
3. Treats HTTP 200 as *not necessarily* success - it then greps the HTML
   body for the literal string `VAR ERROR_MSG` to detect an in-band login
   failure (rpc.py:94-103). There is no structured error response; failure
   detection is regex-on-HTML.

**Every other call goes through one generic RPC method**, `PiazzaRPC.request`
(rpc.py:525-572): `POST` to `https://piazza.com/logic/api` (or
`https://piazza.com/main/api` for a couple of calls - `base_api_urls`,
rpc.py:30-33) with a JSON body `{"method": <name>, "params": {nid_key: nid,
**data}}`; a `logic`-type call also appends `?method=<name>&aid=<nonce>` to
the URL, where the nonce is a real, tiny algorithm in `piazza_api/nonce.py`
(base-36 encoding of `time.time()*1000` plus a random tail) - reproduced
here as `_nonce()`, cited from that exact file. A failure is signalled by a
`{"error": ...}` field in the (HTTP 200) JSON body, not by HTTP status
(`PiazzaRPC._handle_error`, rpc.py:587-604).

**Courses ("networks"), real field names**, from `Piazza.get_user_classes`
(piazza_api/piazza.py:66-89): one `method="user.status"` call returns a dict
with `id` (the user's own id) and `networks` (a list of raw class dicts).
The library reads exactly these keys off each raw class dict: `name`,
`term`, `course_number` (via `.get(..., '')` - i.e. sometimes absent),
`id` (the network id, "nid"), and `prof_hash`. `to_course` below reads the
same four fields.

**A feed of posts is one call away, but only gives you an id.**
`Network.get_feed`/`get_my_feed` (piazza.py's `network.get_my_feed` method,
rpc.py:388-412) returns a `{"feed": [...]}` shape. The client's own
`iter_all_posts` (piazza_api/network.py:85-112) treats each feed entry as
opaque past its `id` - `cids = [post['id'] for post in feed["feed"]]` - and
says explicitly in its own docstring: *"This method does not go against a
bulk endpoint; it retrieves each post individually"* (network.py:88-90,
quoted verbatim). So **whether a feed entry already carries enough fields
to skip a second call (pinned status, folder, timestamp) is a real gap the
client's own source never resolves** - it always re-fetches full posts one
at a time via `content.get`. This adapter does the same, capped by a
`limit` argument to stay polite about repeated per-post calls (the same
"don't hammer an external source in a loop" instinct AGENTS.md states for
the Bookstore, generalised here since nothing in api-standards.md sets a
Piazza-specific rate limit).

**Full post field names, real and cited**: not from rpc.py or network.py
(neither documents the shape of what `content.get` returns beyond "a
dict"), but from the piazza-api repo's own
`data_descriptions/Piazza_API_Post_Data_Dictionary.md` - a file the
maintainers ship in the same repo specifically to enumerate real response
fields. Confirmed real, relevant fields: `id`, `folders` (list of str),
`created` (ISO-8601 string), `type` (`"note"|"question"|"poll"`),
`bucket_name` (e.g. `"Pinned"`, `"Today"`, `"Yesterday"`), `tags` (list of
str, including the literal string `"pin"` when the post is pinned and
`"instructor-note"` when an instructor wrote it), and `history`/`history_size`
- a list of `history_changes` dicts, each with its own `subject` (innerHTML
string) and `created` timestamp for that revision. **The dictionary's own
heading capitalises the key `History`**, but every other real field name in
the same client is lower_snake_case, so this adapter reads `history` first
and falls back to `History` - flagged `[unverified]` casing, not asserted.
Top-level `subject`/`content` are NOT listed in that dictionary at all -
the first entry of `history` is the real place a post's original subject
lives, per the dictionary's own `history_changes` shape.

## The decision this file has to make: browser-session vs. direct POST

`hub/site.py`'s shared core assumes a student logs in themselves in a real
browser window and we reuse that session (Playwright `storage_state`) -
exactly the pattern this project already moved Canvas to, specifically
because a UBC-style CWL/SSO front end doesn't hand out a plain
username+password to POST directly (see PR #16, and `hub/moodle.py`'s
module docstring, which faced the identical fork in the road for Moodle and
reached the same conclusion for the same reason).

Piazza is a different shape of risk than Moodle, though, and it's worth
being explicit about why the same conclusion still holds:
- Moodle is self-hosted per institution, so *some* schools front it with
  campus SSO and some don't - genuinely unknown per-institution.
- Piazza is the opposite: it's one single hosted service at `piazza.com`
  that owns its own account system (the login piazza-api's `user_login`
  POSTs to, `https://piazza.com/class`, IS Piazza's native login, not an
  SSO redirect target). Piazza does support optional SAML/SSO for some
  institutional networks, but the *default*, and what piazza-api's own
  source assumes, is Piazza's own email+password. **[unverified per UBC
  network]** whether any specific UBC Piazza class is SSO-enabled.
- Reusing piazza-api's exact direct-POST mechanism as our *primary* path
  would mean this project's own code receives a raw Piazza password every
  time, in-process - even though we'd never persist it, that's a strictly
  worse guarantee than every other adapter here gives (Canvas, Moodle,
  PrairieLearn, WeBWorK, Brightspace: the password only ever touches a
  real login page rendered by the site itself, inside the browser window
  `hub.site.login` opens - never our code). It would also silently break
  for the SSO-enabled minority of networks, with no way to tell in advance
  which networks those are.
- The browser-session path costs nothing extra here: pointing
  `hub.site.login` at `https://piazza.com` opens a real browser at
  Piazza's own login surface, whatever it is for that student's network -
  Piazza's native form if there's no SSO, or a redirect through the
  institution's IdP if there is. Either way, the password only ever goes
  into a page Piazza (or the school) actually rendered, exactly the
  guarantee this project has kept everywhere else.

So: **browser-session reuse (`hub.site`) is the primary path here too**,
for the same reason `hub/moodle.py` chose it - "works either way" beats
"only works in the narrower case" - even though, unlike Moodle, Piazza's
*default* case doesn't actually need it. `login_with_credentials` below
implements piazza-api's real direct-POST flow anyway, clearly marked as a
fallback for a network confirmed to have no SSO in front of it, mirroring
`hub/moodle.py`'s `fetch_via_token` fallback shape exactly.

## Items: no real due-date field exists at all

Nothing in any real shape found above - not the class dict, not the feed
entry, not the full post, not the history entry - is date-shaped in the
"this is when something is due" sense; `created`/`history[].created` are
posting timestamps, not deadlines. This is the same honest gap
`hub/brightspace.py` hit (no due-date endpoint found after real checking) -
except here, unlike Brightspace, there IS something worth surfacing: a
pinned or instructor-authored post is exactly the "real exam/deadline info
that doesn't appear in the LMS's own structured data" pattern
`hub/syllabus.py` was built around for Canvas announcements. The difference
is *how* you'd get a date out of it: `hub/syllabus.py` hands free text to an
LLM because ordinary syllabus/announcement prose has no fixed shape - and
that needs a new dependency (`anthropic`) and the student's own API key,
both out of scope for this file (the task deliberately keeps new
dependencies to "truly needed"). A regex, the other option, is exactly what
`hub/webwork.py`'s module docstring warns against when there's no fixed
format to anchor it to (WeBWorK's date regex works because WeBWorK always
prints the same three sentences; a Piazza post is free-form human writing).
So: **`to_item` below returns real pinned/instructor posts as `Item`s with
`due=None`, `kind="announcement"` (already an existing, real
`CATEGORY_FOR` entry in `hub/models.py` - categorises as `"task"`)** -
surfaced honestly, never a fabricated date. Wiring in `hub/syllabus.py`'s
LLM extraction as a second pass over these same posts is a real, obvious
future improvement, not attempted here.

Try it:  uv run python -m hub.piazza
"""
import json
from random import random as _random
from string import ascii_letters as _ascii_letters
from string import digits as _digits
from time import time as _time

import requests

from hub import site
from hub.models import Course, Item, category_for

BASE = "https://piazza.com"
SITE = "piazza"

# Real, cited from piazza_api/rpc.py:30-33 (PiazzaRPC.__init__.base_api_urls).
LOGIC_API = f"{BASE}/logic/api"
MAIN_API = f"{BASE}/main/api"

# How many feed posts per class we'll follow up on with a full content.get
# call - see module docstring's "only gives you an id" section for why a
# second call per post is unavoidable, and why that means a cap.
DEFAULT_POST_LIMIT = 40

_EXRADIX_DIGITS = _digits + _ascii_letters


def _int2base(x, base):
    """Real, cited verbatim (renamed to a private helper) from
    piazza_api/nonce.py's `_int2base` - reproduced rather than imported
    since piazza-api isn't a project dependency (see module docstring:
    we reuse its documented shapes, not its `requests.Session`-based
    client, since hub.site's session is a Playwright request context)."""
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
    """Real algorithm, cited from piazza_api/nonce.py's `nonce()`: a
    base-36 encoding of the current time in milliseconds, plus a base-36
    encoded random tail. Piazza's real `logic/api` endpoint takes this as
    an `aid` query parameter on every call (rpc.py:556-562)."""
    part1 = _int2base(int(_time() * 1000), 36)
    part2 = _int2base(round(_random() * 1679616), 36)
    return f"{part1}{part2}"


def login():
    """Open a visible browser at piazza.com; the student signs in (Piazza's
    own login form, or their institution's SSO if that network has it
    enabled); save the session. See the module docstring's "browser-session
    vs. direct POST" section for why this - not `login_with_credentials` -
    is the primary path."""
    site.login(SITE, BASE)


def to_course(network):
    """One raw class dict from `user.status`'s real `networks` list -> a
    Course. Real field names, cited from `Piazza.get_user_classes`
    (piazza_api/piazza.py:66-89): `name`, `term`, `course_number` (often
    absent - `.get(..., '')` in the real source), `id`. Piazza has no
    native "section" concept the way Canvas/Workday do, so section is
    always blank.
    # ponytail: `course_number` is genuinely absent on some real classes
    # per the library's own `.get(..., '')` - falls back to `name` so a
    # course still gets a usable code rather than an empty one.
    """
    return Course(
        code=network.get("course_number") or network.get("name", ""),
        section="",
        term=network.get("term", ""),
        title=network.get("name", ""),
    )


def _history_subject(post):
    """The post's original subject line, real per the data dictionary:
    top-level `subject`/`content` don't exist - the first `history` entry
    (or the doc's own capitalised `History`, since that casing is
    `[unverified]` - see module docstring) carries the real subject as
    innerHTML. Returns "" if genuinely absent rather than guessing."""
    history = post.get("history") or post.get("History") or []
    if not history:
        return ""
    return history[0].get("subject", "") or ""


def _is_pinned_or_instructor(post):
    """Real signal for "worth surfacing", per the data dictionary's `tags`
    field: `"pin"` for a pinned post, `"instructor-note"` for one an
    instructor wrote; `bucket_name == "Pinned"` is the same real signal
    the web UI itself buckets pinned posts under, checked as a fallback in
    case `tags` is empty on a given real response (both are documented,
    which is real but the dictionary is not exhaustive, hence checking
    both rather than trusting only one)."""
    tags = post.get("tags") or []
    return "pin" in tags or "instructor-note" in tags or post.get("bucket_name") == "Pinned"


def to_item(post, course_code, nid=""):
    """One full post dict (a real `content.get` response, per the data
    dictionary) -> an `Item`, or `None` if it isn't pinned/instructor
    content (see module docstring: nothing else here is worth surfacing
    without a due date). `due` is always `None` - see module docstring's
    "Items: no real due-date field exists at all" section for why that's
    honest, not a gap in this function.

    `url` follows Piazza's ordinary web-UI post link shape,
    `<BASE>/class/<nid>?cid=<post id>` - **[reasoned, not from the
    piazza-api source]**: piazza-api is an API client, not a web app, and
    never constructs a browser-facing URL anywhere in its own code. `id` is
    real and unique per post (data dictionary: "unique id/hash of the given
    primary thread"), so even if the exact URL shape here turns out wrong,
    `url` still can't collide across posts or across classes - the real bug
    hub/webwork.py's first draft had (two items both getting `url=""` and
    colliding under hub/db.py's `UNIQUE(source, url)`) can't repeat here.
    """
    if not _is_pinned_or_instructor(post):
        return None
    cid = post.get("id", "")
    kind = "announcement"
    return Item(
        course=course_code,
        category=category_for(kind),
        kind=kind,
        title=_history_subject(post) or "(untitled post)",
        due=None,
        url=f"{BASE}/class/{nid}?cid={cid}",
        source=SITE,
        done=None,  # no completion/read signal in scope here
    )


def _call(req, method, data=None, nid=None, nid_key="nid", api_type="logic"):
    """Real generic RPC shape, cited from `PiazzaRPC.request`
    (piazza_api/rpc.py:525-572): POST a `{"method", "params"}` JSON body to
    `logic/api` (with a `?method=&aid=<nonce>` query string) or `main/api`.
    `req` is hub.site's Playwright request context, not piazza-api's own
    `requests.Session` - reusing the documented endpoint/body shape without
    importing the library itself (which brings its own, different, session
    type).

    Failure detection: `[reasoned]`, not confirmed. Real piazza-api never
    tests for an *expired* session by response shape at all - it only
    guards client-side, before ever sending a request, on whether any
    cookie exists at all (`_check_authenticated`, rpc.py:578-585). What an
    actually-expired session's response looks like is a genuine gap.
    Conservatively, this treats a non-OK HTTP status OR a JSON body with a
    real `error` field (the one documented failure shape,
    `_handle_error`, rpc.py:587-604) as "not logged in" and lets
    `hub.site.fetch_with_session` retry the login once - harmless even if
    the real cause was a different kind of failure, since that's a no-op
    retry either way.
    """
    endpoint = LOGIC_API if api_type == "logic" else MAIN_API
    if api_type == "logic":
        endpoint = f"{endpoint}?method={method}&aid={_nonce()}"
    body = json.dumps({"method": method, "params": dict({nid_key: nid}, **(data or {}))})
    r = req.post(endpoint, data=body, headers={"Content-Type": "application/json"})
    if not r.ok:
        raise site.NotLoggedIn
    result = r.json()
    if result.get("error"):
        raise site.NotLoggedIn
    return result.get("result")


def _posts_for_network(req, nid, course_code, limit):
    """Real feed -> full-post-per-id -> Items, per the module docstring's
    "only gives you an id" section. `get_my_feed`'s real params
    (rpc.py:388-412): `limit`, `offset`, `sort` (only documented value is
    `"updated"`)."""
    feed = _call(req, "network.get_my_feed", nid=nid, data={"limit": limit, "offset": 0, "sort": "updated"})
    cids = [p.get("id") for p in (feed or {}).get("feed", []) if p.get("id")][:limit]
    items = []
    for cid in cids:
        # Real params, cited from `PiazzaRPC.content_get` (rpc.py:126-142):
        # {"cid": cid, "student_view": None}.
        post = _call(req, "content.get", nid=nid, data={"cid": cid, "student_view": None})
        item = to_item(post or {}, course_code, nid) if post else None
        if item is not None:
            items.append(item)
    return items


def _run(req, limit):
    # Real params for user.status: none beyond the implicit nid=None
    # (Piazza.get_user_status calls self.request(method="user.status")
    # with no nid - piazza_api/piazza.py:56-64, rpc.py:517-523).
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
        except site.NotLoggedIn:
            raise  # a genuine session expiry: let fetch_with_session retry the whole run
        except Exception:
            # One network's feed/post call failing (a malformed response, a
            # transient error) must not drop every other network's courses
            # and items along with it - the same "one bad entity nukes
            # everything" bug just found and fixed in this same review pass
            # for hub/google_classroom.py and hub/ed_discussion.py.
            continue
    return courses, items


def fetch(limit=DEFAULT_POST_LIMIT):
    """Return (courses, items) for the student's own Piazza classes. Logs
    in (opens a browser window) if there's no saved session. Never raises:
    any login/parse/network failure returns ([], []), same as every other
    adapter here (AGENTS.md, "handle failure without crashing")."""
    try:
        return site.fetch_with_session(SITE, BASE, lambda req: _run(req, limit))
    except Exception:
        return [], []


# --- Fallback path: piazza-api's real direct email+password flow ----------
# [Real, cited from piazza_api/rpc.py's PiazzaRPC.user_login, lines 55-103 -
# see module docstring for the full call sequence.] NOT what fetch() uses.
# Only appropriate for a Piazza network confirmed to have no SSO in front of
# it - see the module docstring's "browser-session vs. direct POST" section.
# Mirrors hub/moodle.py's fetch_via_token fallback shape: the password is
# used once, in memory, to get a session cookie; it is never stored.
def login_with_credentials(email, password):
    """Direct email+password -> a `requests.Session` with Piazza's real
    session cookie, or `None` on any failure. Reproduces piazza-api's own
    `user_login` call sequence exactly (see module docstring), rather than
    depending on the `piazza-api` package, since this project adds
    dependencies only when truly needed (AGENTS.md) and everything used
    here is three small, cited real calls.
    """
    try:
        session = requests.Session()
        csrf_response = session.get(f"{BASE}/main/csrf_token", timeout=30)
        if "CSRF_TOKEN" not in csrf_response.text.upper():
            return None
        csrf_token = csrf_response.text.translate({34: None, 59: None}).split("=")[1]
        login_response = session.post(
            f"{BASE}/class",
            data={
                "from": "/signup",
                "email": email,
                "password": password,
                "remember": "on",
                "csrf_token": csrf_token,
            },
            timeout=30,
        )
        if login_response.status_code != 200 or "VAR ERROR_MSG" in login_response.text.upper():
            return None
        return session
    except Exception:
        return None


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:15} {c.title}")
    print()
    for i in items:
        print(f"{i.category:9} {i.kind:12} {i.course:15} {i.title}")
