"""Crowdmark adapter: `login()` is real and built; `fetch()` is a deliberate,
honest stub. Read this whole docstring before changing either.

Crowdmark is primarily a **grading/submission** tool -- students submit scanned
or typed work and an instructor grades it -- not a due-date tracker the way
hub/prairielearn.py or a WeBWorK adapter would be. That distinction, and
everything else below, comes from Crowdmark's own public help docs and UBC's
Learning Technology Hub (LT Hub), not from a live account: nobody on this team
currently has one to check with real devtools, unlike hub/brightspace.py, which
*was* checked against a real UBC account.

**Cited from real sources:**

- A persistent, reusable login exists -- this is NOT purely per-assessment
  magic-link access. A student gets a one-time "claim your account" email the
  very first time (crowdmark.com/help/claiming-your-account/), but after that
  signs in at a normal URL that works any time:
  `https://app.crowdmark.com/sign-in/<institution>` -- UBC's own slug is
  confirmed live: `https://app.crowdmark.com/sign-in/ubc`. That page offers
  "Sign in with <your school's LMS>" (SSO) or email+password
  (crowdmark.com/help/signing-in-to-crowdmark/).
- UBC's own student-facing guide confirms the Canvas-SSO path specifically for
  UBC: "UBC students can access Crowdmark by logging in to
  app.crowdmark.com/sign-in/ubc and selecting the option to sign in with
  Canvas." (lthub.ubc.ca, "Crowdmark Student Guide").
- After signing in, Crowdmark's own docs say a student lands on a real,
  named "My Courses" page (crowdmark.com/help/signing-in-to-crowdmark/). That
  page's *existence* is cited; its *shape* is not -- no source says whether
  it's a plain JSON endpoint or a client-rendered SPA calling some internal,
  undocumented API, and there's no live account to open devtools on it and
  check. AGENTS.md's rule for a logged-in site is "read its JSON, never its
  HTML" -- there is no citable JSON shape for "My Courses" to read, so this
  file does not scrape it and does not invent an endpoint for it.
- Due dates ARE shown to students -- but confirmed only *inside* one
  individual assessment: "a deadline... by clicking on the due date at the
  top", plus a countdown timer once it's opened
  (crowdmark.com/help/what-will-students-see-after-i-distribute-the-assessment/;
  crowdmark.com/help/completing-and-submitting-an-assessment/). No source
  confirms a due date appears in "My Courses" or any other list/dashboard
  view. If due dates genuinely only exist one HTTP round-trip per assessment,
  with no listing to enumerate them from, that's a much heavier and different
  shape of adapter than anything else in `hub/` -- not something to build on
  a guess.
- **UBC-specific wrinkle, found while checking this, not asked for:** UBC's LT
  Hub ended *central* support/licensing for Crowdmark after April 30, 2024
  ("Central support for Crowdmark ending in April 2024",
  lthub.ubc.ca/2023/06/21/central-support-for-crowdmark-ending-april-2024/ --
  that URL now 404s, consistent with support having fully wound down since).
  Individual instructors or faculties may still run their own paid licence
  (the task that produced this file names UBC Engineering as one), but
  Crowdmark is no longer a guaranteed-available, centrally-integrated UBC tool
  the way Canvas is. Unlike Brightspace, there is no one "real UBC course"
  this adapter was checked against live -- treat everything below the login
  page as unverified for UBC specifically, even though the underlying
  Crowdmark product behavior is well documented in general.

**Reasoned by analogy (not directly cited):** hub.site.login's "open `base`,
wait to land back on `base` past a `/login` redirect, save the session" should
work for Crowdmark's LMS-SSO path the same way it already does for Canvas and
hub/prairielearn.py, since UBC's Crowdmark SSO is also fronted by the same
Canvas/CWL-style flow -- but this is inferred from the shared login
technology, not tested against a real Crowdmark session.

**Genuinely unknown:** whether "My Courses" (or anything else reachable once
logged in) exposes courses or assessments as JSON at all; if so, its shape,
its course-code format (for matching against Canvas/Workday), and whether due
dates appear there or truly only per-assessment.

**What this file does, given all of that:** `login()` is a real, ordinary
"browser session" adapter, built the same way as Canvas/PrairieLearn, because
the sign-in URL and SSO option above are genuinely citable. `fetch()` is
deliberately left as an honest stub -- same spirit as hub/brightspace.py's "not
built here, on purpose" for due dates -- returning `([], [])` always, rather
than scrape "My Courses" HTML (forbidden by AGENTS.md rule 6) or invent a JSON
endpoint nobody has seen. Revisit once someone with a real Crowdmark account
opens devtools on "My Courses" and reports back what's actually there.

Sources:
- https://www.crowdmark.com/help/claiming-your-account/
- https://www.crowdmark.com/help/signing-in-to-crowdmark/
- https://www.crowdmark.com/help/completing-and-submitting-an-assessment/
- https://www.crowdmark.com/help/what-will-students-see-after-i-distribute-the-assessment/
- https://lthub.ubc.ca/guides/crowdmark-student-guide/
- https://lthub.ubc.ca/2023/06/21/central-support-for-crowdmark-ending-april-2024/ (now 404 -- see note above)
- https://app.crowdmark.com/sign-in/ubc (live sign-in page; confirms the "ubc" institution slug)

Try it:  uv run python -m hub.crowdmark <base-url>
"""
from urllib.parse import urlsplit

from hub import site

SITE = "crowdmark"


def _origin(base):
    """Normalise `base` to just scheme://host. Crowdmark is multi-tenant the
    same way hub/brightspace.py's Brightspace is -- an institution slug lives
    in the URL path (e.g. "/sign-in/ubc"), not in the hostname the way
    canvas.ubc.ca is for Canvas -- so `base` may be a bare origin or a full
    sign-in URL, and either normalises to the same origin here."""
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}"


def login(base):
    """Open a visible browser at `base` (e.g.
    "https://app.crowdmark.com/sign-in/ubc"); the student signs in, via UBC's
    Canvas-SSO option or email+password (both cited in the module docstring);
    save the session. This reuses hub.site.login exactly as Canvas and
    hub/prairielearn.py do, because Crowdmark's sign-in is a normal, reusable
    page -- not a one-off per-assessment magic link. See the module
    docstring's "Cited from real sources" section for why that's a citable
    claim rather than an assumption."""
    site.login(SITE, _origin(base))


def fetch(base):
    """Deliberately unimplemented. See the module docstring's "What this file
    does" section for exactly why: there's no citable JSON shape for
    Crowdmark's "My Courses" page to read, and AGENTS.md rule 6 forbids
    scraping a logged-in site's HTML instead. Returns `([], [])` rather than
    guess -- never crashes the dashboard either way (AGENTS.md "handle
    failure without crashing"). `base` is accepted (and unused) only so this
    adapter has the same call shape as every other one in `hub/`."""
    return [], []


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: uv run python -m hub.crowdmark <base-url>")
        raise SystemExit(1)
    courses, items = fetch(sys.argv[1])
    print("(no courses/items yet -- see hub/crowdmark.py's module docstring)")
