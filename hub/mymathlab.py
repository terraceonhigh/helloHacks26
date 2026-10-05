"""Pearson MyLab & Mastering adapter -- NOT BUILT HERE, ON PURPOSE.

"MyMathLab" is the old marketing name for what Pearson now sells as one of
70+ subject-specific "MyLab"/"Mastering" products (MyLab Math, Mastering
Chemistry, ...) under one shared platform. Unlike WeBWorK or PrairieLearn,
MyLab/Mastering is closed-source and Pearson publishes no developer
documentation of its internal page structure, DOM, or any student-facing
API. Everything below is either cited from a real public source, reasoned
by analogy to hub/prairielearn.py's browser-session pattern, or flagged as
genuinely unknown. **My confidence here is lower than the first WeBWorK/
PrairieLearn drafts had** -- nobody on this team has an active MyLab course
to check any of this against a live account.

## What's cited (real, linked sources)

- Access path is LTI, launched from the institution's LMS, with the LMS
  handling authentication ("single sign-on"): "With single sign-on through
  your Learning Management System into Pearson, students are ready on their
  first day." Pearson also states it does "NOT store any institutional data
  with the exception of anonymized user IDs and Course IDs" for grade sync.
  Supported LMSs listed: Canvas, Blackboard, Brightspace by D2L, Moodle,
  Schoology, Sakai. Pearson describes itself as "LTI Certified" (IMS
  Global/1EdTech), supporting both "LTI 1.3 / LTI Advantage" and an "LTI 1.1
  Legacy Integration".
  https://www.pearson.com/en-us/higher-education/educators/digital-learning-platforms/lms-integration-services.html
- Some institutions instead point students at a *direct* Pearson login
  (registration.mypearson.com / mylabprograms.pearson.com) with a
  course/access code from the instructor, independent of the LMS -- this is
  the older, non-LTI path and still documented as an option today.
  https://registration.mypearson.com/ , https://mylabprograms.pearson.com/
  Which path a given course/institution uses is a per-course instructor
  setting we cannot know in advance -- see login()'s docstring.
- MyLab/Mastering is Pearson-owned and marketed as "MyLab and Mastering
  series," 70+ subject products; MyMathLab is one of them, now folded into
  that shared brand. https://en.wikipedia.org/wiki/MyMathLab
- A cited accessibility guide notes screen readers "can read the Calendar,
  Results, Announcements, Study Plan topics, and list of available
  assignments" on the student side, which at least confirms those are named
  sections of the student UI (not their URLs, DOM, or field names).
  https://ysu.edu/sites/default/files/mathematics-achievement-center/Pearson%20Accessibility%20User%20Guide.pdf
  **[secondary: content not machine-readable when fetched for this PR --
  taken from a search-engine snippet of that PDF, not a direct read. Treat
  this one claim as weaker than the others above.]**
- No public developer API: a search for "Pearson MyLab public API developer
  documentation" surfaces only https://github.com/pearsonapi (an
  organization with no MyLab-specific client) and Pearson's own product
  pages -- nothing resembling docs/api-standards.md's Canvas or Moodle
  entries. **[unverified further than "we found nothing"]**

## What's reasoned by analogy, not confirmed

- IF a course happens to be reachable at a stable, session-authenticated
  URL after LTI launch (the way hub.prairielearn reuses a CWL session for
  plain GETs), the same hub.site.fetch_with_session pattern could apply.
  This is unverified: an LTI launch is commonly a one-time signed POST
  redirect into an iframe/new tab with a session tied to that launch, which
  may not be revisitable by a saved Playwright storage_state the way
  Canvas/PrairieLearn's plain CWL cookie is. This is the single biggest
  open question standing between this stub and a real fetch().

## What's genuinely unknown (a human with a real MyLab account must check first)

1. Does re-opening `base` in a browser with a saved session land back on the
   assignment list without re-launching through the LMS? (If not, hub.site's
   "reuse a saved session" model doesn't fit MyLab at all, and this adapter
   would need to drive the LMS's launch link every time instead.)
2. The real URL of the student assignment/study-plan list once inside a
   course (LTI launches typically land on a Pearson-hosted URL under a
   per-institution or per-course path we have no sample of).
3. Whether that page is server-rendered HTML (scrapeable, like PrairieLearn)
   or a JS single-page app that only talks to internal, unversioned XHR
   endpoints (in which case a login()-only Playwright approach might still
   work by reading those XHR responses, but we don't know their shape).
4. Actual due-date formatting, per-assignment status ("done"), and a stable
   unique-per-assignment URL for hub.db's `UNIQUE(source, url)` constraint --
   guessing at this without a sample almost guaranteed a repeat of the exact
   `url=""` collision bug this task was written to avoid (see hub/db.py).

Given all of that, this module intentionally stops at login(). fetch()
returns ([], []) rather than parse a page structure invented with no basis.
Once someone here has a real MyLab course, the fix is: log in, open browser
devtools, save one real assignment-list page (HTML or the XHR JSON behind
it) into fixtures/, and write to_course/to_item against that real sample --
same as hub/prairielearn.py's docstring describes for its own verification.

Try it:  uv run python -m hub.mymathlab
"""
from hub import site

BASE = "https://mylab.pearson.com"  # ponytail: unconfirmed generic landing host: real courses launch to a
# per-institution/per-course URL via LTI or a direct mypearson.com login (see module docstring); this is
# only a placeholder so login() has something to open until a human confirms their own course's real URL.
SITE = "mymathlab"


def login(base=BASE):
    """Open a visible browser at `base`; the student signs in; save the session.

    Which access path `base` should actually be is unconfirmed and varies per
    institution/course (see module docstring):
    - LTI-launched: `base` would be the LMS's course page with the MyLab/
      Mastering link, and "logged in" would mean landing back on Pearson's
      side of that launch -- closer to how hub.canvas/hub.prairielearn
      launch through UBC's CWL-fronted LMS today.
    - Direct Pearson login: `base` would be a mypearson.com/pearson.com
      sign-in page taking an institution- or course-specific access code,
      independent of any LMS.
    Pass the real URL for your own course; there is no single correct
    default (BASE above is a placeholder, not a confirmed endpoint).
    """
    site.login(SITE, base)


def fetch(base=BASE):
    """Return ([], []) -- see the module docstring's "genuinely unknown"
    section for exactly what a human with a real MyLab account needs to
    check before this can parse anything. Deliberately conservative: with
    no confirmed page structure to defend against, guessing at a parser
    risks exactly the kind of silent-garbage-or-crash failure
    AGENTS.md asks every adapter to avoid, and the empty-`url` collision
    hub/db.py's `UNIQUE(source, url)` would punish (see hub/db.py).
    """
    return [], []


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    db.save(db.connect(), courses, items)
    print(f"mymathlab: {len(courses)} courses, {len(items)} items (stub -- see hub/mymathlab.py docstring)")
