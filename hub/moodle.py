"""Moodle adapter (other schools; UBC runs Canvas, not Moodle).

**[UNVERIFIED END-TO-END]** Nobody on this project has a live Moodle account
anywhere, at UBC or another school. Every claim below comes from Moodle's own
published developer docs (linked from docs/api-standards.md's Moodle section,
which was already researched before this file existed - not re-derived here),
never from hitting a real site. Treat every function here as needing a real
account to confirm before it ships to an actual student.

**Why browser-session + AJAX, not token.php + password, is the primary path:**
Moodle's documented, official path for a student-facing app is the Mobile Web
Services REST API: POST username+password to `login/token.php` for a
`wstoken`, then call `webservice/rest/server.php?wstoken=...&wsfunction=...`.
That's real and simple - *for a Moodle site that owns its own login form*.
Many Canadian institutions instead front Moodle with campus SSO
(Shibboleth/CAS/SAML): the student's password lives with the identity
provider, not Moodle, so there is no Moodle-native username+password to POST
in the first place, and token.php's own login form gets bypassed or disabled
under that setup. This project already hit that exact wall once with Canvas
(see PR #16: Canvas moved from a direct API-token flow to browser-session
reuse specifically because a UBC-style CWL/SSO front end doesn't hand out
credentials to POST directly), and every adapter since (`hub/canvas.py`,
`hub/prairielearn.py`) reuses `hub.site`'s "open a real browser, the student
logs in themselves, save the session" pattern for exactly that reason. Since
we have no live Moodle site to test against and can't know in advance whether
a given institution's Moodle sits behind SSO, defaulting to the same
browser-session pattern is the safer bet - it works either way (SSO or
Moodle's own login page), where the direct-credential flow only works in the
narrower case. `fetch_via_token` below implements the official token.php
flow anyway, clearly labelled as a fallback for a small self-hosted Moodle
that is *not* behind SSO - not what `fetch()` uses.

**Why `/lib/ajax/service.php`, not the mobile REST API, once we have a
session:** the mobile REST API needs a `wstoken`, and the normal way to get
one *is* token.php - the very form we just avoided. Some Moodle configs let a
logged-in user view/regenerate their own mobile token on a page in the site
(`user/managetoken.php`), but reading that would mean scraping HTML behind a
login to pull out a credential, which is exactly what AGENTS.md rule 6 rules
out ("Behind CWL ... Hub reads only the site's JSON with that session, never
its HTML"). Moodle's own web UI does not use the mobile REST API for itself
either - every page you see as a logged-in user (calendar, dashboard,
gradebook) is rendered by calling `/lib/ajax/service.php` with the browser's
own session cookie plus a `sesskey` (a per-session CSRF-style value Moodle
embeds in every page's JS config object, `M.cfg.sesskey`), POSTing the same
`wsfunction` names as the mobile API as a JSON batch, and reading back JSON.
That is "read JSON behind the session, same as Canvas's `/api/v1`" - no
token, no password, no HTML parsed for its content (we only regex out one
CSRF-style field from the page's own JS config, the same category of thing a
browser does automatically on every page load, not "the site's HTML" in the
rule 6 sense of scraping displayed content). This is real, documented Moodle
internal plumbing (Moodle core's own `core/ajax` JS module talks to exactly
this endpoint - see the "Creating a web service client" dev doc linked in
docs/api-standards.md), but whether a *given* institution's Moodle allows
these particular `wsfunction`s to be called this way (some functions are
gated behind "AJAX allowed" flags) is genuinely unverified per-institution,
so it is marked `[unverified]` throughout rather than asserted as fact.

Scope actually implemented: courses (`core_enrol_get_users_courses`) and a
single richer feed of due items (`core_calendar_get_action_events_by_timesort`,
Moodle's closest analog to Canvas's planner/items - one call, every module
type, real due timestamps). `mod_assign_get_assignments` (per-assignment
detail) and `gradereport_user_get_grade_items` (grades) are documented in
docs/api-standards.md and callable the same way, but are deliberately left
for a follow-up once someone can verify field shapes against a live site -
guessing grade-report JSON shape with zero ground truth felt worse than
shipping less. Course.grade is always None here, on purpose.
"""
import json
import re
from datetime import datetime, timezone

import requests

from hub import site
from hub.models import Course, Item, category_for

SITE = "moodle"

# Moodle embeds a JS config object on every logged-in page, e.g.
# `M.cfg = {"wwwroot":"https:\/\/moodle.example.edu","sesskey":"AbCd1234",...}`.
# We only ever pull the sesskey (a CSRF-style token, not a credential) back
# out of it - never parsed as HTML, never displayed content. [unverified]:
# real Moodle installs vary in exact page layout; this regex targets the
# `M.cfg` shape documented across Moodle's own JS/theming docs.
SESSKEY_RE = re.compile(r'"sesskey"\s*:\s*"(\w+)"')

# Moodle's modname -> our kind. Unlisted module types default to "assignment",
# same "safest bucket, still a task" convention as hub/canvas.py's KINDS.
KINDS = {"quiz": "quiz", "assign": "assignment"}


def login(base):
    """Open a visible browser at `base`; the student signs in (their
    institution's own login page, SSO or not); we save the session. Mirrors
    hub.canvas.login/hub.prairielearn.login exactly."""
    site.login(SITE, base)


def to_course(c):
    """core_enrol_get_users_courses course dict -> Course. [unverified field
    shape - built from Moodle's documented external function definition, not
    a live response.] Moodle courses have no native "term"/section concept
    the way Canvas/Workday do.
    # ponytail: term left blank until a real Moodle response shows something
    # usable (category name? a custom course-info field?) to fill it from.
    """
    return Course(
        code=c.get("shortname", ""),
        section="",
        term="",
        title=c.get("fullname", ""),
        grade=None,  # gradereport_user_get_grade_items not implemented yet - see module docstring
    )


def to_item(e):
    """core_calendar_get_action_events_by_timesort event dict -> Item.
    [unverified field shape.] Each event embeds its own course sub-object
    (Moodle's documented pattern for this external function), so - unlike
    Canvas's planner/items - no separate course_id -> code lookup is needed.

    `url` is Moodle's own per-event link, already unique per event/module
    instance; when a response is missing it (shouldn't happen per the docs,
    but nothing here is verified), we fall back to Moodle's real
    `calendar/event.php?id=<event id>` route keyed on the event's own id
    rather than ever emitting the same empty url twice - hub/webwork.py's
    first draft did that and silently overwrote items in hub.db (see
    hub/db.py's UNIQUE(source, url)); this adapter must not repeat it.
    """
    course = e.get("course") or {}
    kind = KINDS.get(e.get("modulename", ""), "assignment")
    timesort = e.get("timesort")
    event_id = e.get("id")
    return Item(
        course=course.get("shortname", ""),
        category=category_for(kind),
        kind=kind,
        title=e.get("name", ""),
        due=datetime.fromtimestamp(timesort, tz=timezone.utc) if timesort else None,
        url=e.get("url") or f"calendar/event.php?id={event_id}",
        source="moodle",
    )


def extract_sesskey(page_text):
    """Dashboard page text -> the `M.cfg.sesskey` CSRF-style value Moodle
    embeds in its own JS config on every logged-in page, or None if it isn't
    there (session isn't actually logged in). Pulled out with a regex, not a
    full HTML parse - we never read the page's displayed content, only this
    one JS-config field, same as a browser reading its own page's config."""
    m = SESSKEY_RE.search(page_text)
    return m.group(1) if m else None


def _sesskey(req, base):
    r = req.get(f"{base}/my/")  # dashboard: always rendered for a logged-in user
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"{base}/my/ -> {r.status}")
    key = extract_sesskey(r.text())
    if key is None:
        raise site.NotLoggedIn  # no sesskey on the page => session isn't actually logged in
    return key


def _ajax(req, base, sesskey, calls):
    """POST a batch of {methodname, args} to Moodle's internal AJAX
    multiplexer, same call shape Moodle's own core/ajax JS module uses.
    Returns the list of per-call {error, data} results, in call order.
    """
    payload = [{"index": i, "methodname": c["methodname"], "args": c.get("args", {})}
               for i, c in enumerate(calls)]
    r = req.post(f"{base}/lib/ajax/service.php?sesskey={sesskey}&info={calls[0]['methodname']}",
                 data=json.dumps(payload), headers={"Content-Type": "application/json"})
    if r.status == 401:
        raise site.NotLoggedIn
    if not r.ok:
        raise RuntimeError(f"lib/ajax/service.php -> {r.status}")
    return json.loads(r.text())


def _run(req, base, start, end):
    sesskey = _sesskey(req, base)
    results = _ajax(req, base, sesskey, [
        {"methodname": "core_enrol_get_users_courses", "args": {"userid": 0}},
        {"methodname": "core_calendar_get_action_events_by_timesort",
         "args": {"timesortfrom": start, "timesortto": end, "limitnum": 100}},
    ])
    course_result, events_result = results
    if course_result.get("error") or events_result.get("error"):
        raise RuntimeError("moodle ajax call reported an error")
    courses = [to_course(c) for c in course_result.get("data", [])]
    items = [to_item(e) for e in events_result.get("data", {}).get("events", [])]
    return courses, items


def fetch(base, start=None, end=None):
    """Return (courses, items) for `base` (a Moodle site's own URL, e.g.
    "https://moodle.example.edu" - unlike hub.canvas, Moodle isn't one fixed
    UBC host, so every caller supplies it). Logs in if there's no saved
    session. Never raises: any login/parse failure returns ([], []) so one
    broken source can't crash the dashboard (AGENTS.md, "handle failure
    without crashing").
    """
    now = datetime.now(timezone.utc)
    start = start if start is not None else int((now.timestamp() - 120 * 86400))
    end = end if end is not None else int((now.timestamp() + 120 * 86400))
    try:
        return site.fetch_with_session(SITE, base, lambda req: _run(req, base, start, end))
    except Exception:
        return [], []


# --- Fallback path: official token.php + wstoken REST flow -----------------
# [unverified, and NOT what fetch() uses.] Only correct for a small,
# self-hosted Moodle that owns its own login (no SSO in front) - see the
# module docstring for why that's a narrower case than the browser-session
# path above. Provided because docs/api-standards.md documents it as the
# "official" mobile-app flow and a future caller may have exactly that kind
# of site. Never wire this to a UBC-fronted or SSO-fronted Moodle.
def fetch_via_token(base, username, password):
    """Direct username+password -> wstoken -> REST JSON. Returns (courses,
    items) like fetch(), or ([], []) on any failure. The password is used
    once, in memory, to get a token; it is never stored (matches
    hub.site's "never see or store the password" rule, just via a different
    mechanism since there's no browser session to persist here instead).

    docs/api-standards.md documents this as a GET with the password as a
    query parameter (Moodle's own docs describe it that way too) -- but
    token.php accepts POST identically, and a URL query string is exactly
    the kind of place a password shouldn't sit (server access logs, proxy
    logs, any library's own debug/request logging). POST with a form body
    avoids that for free, so that's what this sends instead."""
    try:
        r = requests.post(f"{base}/login/token.php", data={
            "username": username, "password": password, "service": "moodle_mobile_app",
        }, timeout=30)
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            return [], []
        courses_raw = _rest_call(base, token, "core_enrol_get_users_courses", {"userid": 0})
        now = datetime.now(timezone.utc)
        events_raw = _rest_call(base, token, "core_calendar_get_action_events_by_timesort", {
            "timesortfrom": int(now.timestamp() - 120 * 86400),
            "timesortto": int(now.timestamp() + 120 * 86400),
            "limitnum": 100,
        })
        courses = [to_course(c) for c in courses_raw or []]
        items = [to_item(e) for e in (events_raw or {}).get("events", [])]
        return courses, items
    except Exception:
        return [], []


def _rest_call(base, token, wsfunction, args):
    params = {"wstoken": token, "wsfunction": wsfunction, "moodlewsrestformat": "json"}
    params.update(args)
    r = requests.get(f"{base}/webservice/rest/server.php", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    from hub import db

    moodle_base = "https://moodle.example.edu"  # replace with a real institution's Moodle URL
    courses, items = fetch(moodle_base)
    db.save(db.connect(), courses, items)
    for c in courses:
        print(f"{c.code:15} {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or datetime.max.replace(tzinfo=timezone.utc))):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:15} {i.title}")
