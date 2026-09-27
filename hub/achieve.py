"""Macmillan Achieve adapter: intentionally a login-only stub. See "Items"
below for exactly why `fetch()` doesn't parse anything yet, and what a human
with a real account would need to check first.

**This is issue #24** ("Macmillan Achieve"), one of the tracked integration
targets alongside WeBWorK (#23) and Moodle (#25) -- expected work, not
scope creep.

**Confidence here is LOWER than hub/webwork.py's first draft.** WeBWorK is
open-source with a real, publicly inspectable page template, so that
adapter's first draft could cite actual markup. Achieve is a closed-source
Macmillan Learning product -- there is no public developer documentation for
its API or internal page structure, and nothing found below came from
inspecting a real, logged-in Achieve session. Everything cited is from
public, logged-out help-center pages describing the *access flow* only, not
the dashboard/assignment-list markup.

**What's real and cited (checked 2026-09-26):**
- Achieve is reached from inside a course's LMS (Canvas/Brightspace/etc.) by
  clicking an Achieve-branded link -- an LTI-launched, single-sign-on flow.
  ("From inside your Canvas course, go to Modules and click on any Macmillan
  Achieve assignment.") -- University of New Mexico, [How to Access Macmillan
  Achieve Assignments](https://canvasinfo.unm.edu/external-apps/students/macmillan-achieve-student/how-to-access-macmillanachieve-assignments.html)
- Unlike hub/webwork.py's UBC deployment (LTI-only, no separate login page
  found), Achieve is confirmed to also have its **own standalone login**,
  independent of any LMS launch: a student can sign in directly at
  `achieve.macmillanlearning.com` with a Macmillan account (e.g. one created
  from a Student Store purchase), or join a course with an instructor-given
  access code from the Achieve sign-in page itself. -- Macmillan Learning
  Student Store, [SSO-Help](https://store.macmillanlearning.com/us/SSO-Help)
  and [Get Help / FAQs](https://store.macmillanlearning.com/us/content/get-help)
  So `login()` below (reusing `hub.site.login`, same as every other
  browser-session adapter) is plausible on its own merits, unlike
  hub/webwork.py's UBC case -- but nobody on this team has actually
  driven it against a real Achieve account to confirm the login page reads
  "logged in" the way `hub.site.login` expects (see its docstring for the
  exact caveat this carries).
- Macmillan's own help center is a Salesforce-hosted site
  (`mhe.my.site.com/macmillanlearning/s/article/...`) that renders its
  articles client-side; several pages searched for a description of the
  actual assignment-list/dashboard UI (registration flow, "join a course")
  returned no usable content when fetched directly -- so nothing about the
  post-login page structure is cited here. That is a real gap, not
  something guessed around.

**What's reasoned by analogy, not confirmed:** if Achieve does end up having
a plain JSON API behind its dashboard (plausible for any modern SPA, the way
hub/brightspace.py found for D2L), that would be the right thing to read --
AGENTS.md's "behind a login, read JSON, never HTML" rule applies here full
force, more so than to WeBWorK/PrairieLearn's legacy server-rendered pages,
since a wrong guess at Achieve's HTML has nothing to check it against.

**What's genuinely unknown:** the dashboard/assignment-list markup or API
shape, whether course/assignment identifiers are stable and URL-shaped
(needed for hub.db's `UNIQUE(source, url)` items table -- see hub/webwork.py's
own comment on this, and AGENTS.md rule 4), whether due dates or scores are
shown anywhere on a page reachable without extra clicks, and how (or
whether) an LTI-launched session persists for a plain follow-up GET the way
WeBWorK's did at UBC.

**What a human with a real Achieve account should check first, before
writing a real parser:**
1. Whether `hub.site.login(SITE, "https://achieve.macmillanlearning.com")`
   actually lands "logged in" per its own definition (back on `base` past
   any `/login` redirect) -- or whether Achieve keeps you on an app shell
   URL that never looks "logged out" to that check.
2. Open the browser's Network tab while loading the assignment
   dashboard: is there a plain JSON endpoint (like Brightspace's), or is it
   only server-rendered HTML (like WeBWorK/PrairieLearn)?
3. If HTML: capture real, anonymised markup for one open assignment, one
   assignment that isn't due yet, and one closed/past-due assignment (the
   three states hub/webwork.py had to distinguish) before writing a parser
   -- don't guess at the class names or structure.
4. Confirm whether each assignment has a stable, unique URL on its own (the
   `(source, url)` identity AGENTS.md rule 4 requires) even before it opens,
   the same problem hub/webwork.py hit and fixed.

Try it:  uv run python -m hub.achieve
"""
from hub import site

SITE = "achieve"
BASE = "https://achieve.macmillanlearning.com"


def login(base=BASE):
    """Open a visible browser at `base`; the student signs in with their
    Macmillan account (or via an access code) and we save the session --
    same `hub.site.login` core every browser-session adapter uses.

    Real caveat, matching hub/webwork.py's own: a student may reach Achieve
    for the first time only by clicking through their course's LMS (Canvas,
    Brightspace, ...) rather than by visiting `base` directly, especially
    before they've created a standalone Macmillan account. Unlike
    hub/webwork.py's UBC deployment, Achieve is confirmed to also offer a
    standalone sign-in page independent of any LMS (see the module
    docstring's citations) -- but nobody on this team has verified live
    that `hub.site.login`'s "back on `base` past any /login redirect" check
    actually succeeds against it. If it doesn't, the fallback is the same
    as WeBWorK's: click through the course's LMS once first, then retry.
    """
    site.login(SITE, base)


def fetch(base=BASE):
    """Intentionally returns `([], [])` always. See the module docstring's
    "Items" -- sorry, "What's genuinely unknown" section for exactly why:
    there is no public documentation of Achieve's dashboard/assignment-list
    structure (JSON or HTML), and nobody on this team has a real Achieve
    account to check it live against, the way hub/webwork.py and
    hub/brightspace.py did for their own first real drafts. Writing a
    parser against guessed markup would risk exactly the kind of confident-
    but-wrong result AGENTS.md's "handle failure without crashing" rule
    exists to avoid -- so this returns the same safe, empty, honestly-
    documented result on every call rather than fabricate one.

    `base` is accepted (not hardcoded) on the expectation that, like
    Brightspace, an institution or student could plausibly reach Achieve
    through a distinct path -- but that's unconfirmed too; the only base
    seen in any real citation is `achieve.macmillanlearning.com` itself.
    """
    return [], []


if __name__ == "__main__":
    courses, items = fetch()
    print(f"{len(courses)} courses, {len(items)} items -- see hub/achieve.py's module docstring for why both are always 0 today")
