# UBC Hub: design spec

Answers Jacky's design prompt ([handoff/jacky-design-prompt.md](handoff/jacky-design-prompt.md)). The API facts behind every decision are in [api-standards.md](api-standards.md), with sources. This is the founding doc for the build. Where it says **Decision**, change it here first, then in code.

---

## 1. Product vision and scope

**UBC Hub is a read-only aggregator.** The student connects each source themselves; Hub pulls from it, normalises the data, and shows one answer to "what do I need to do this week?"

- **Not a middleware or single sign-on layer.** We never hold CWL credentials. Proxying CWL sessions is the riskiest option legally and technically (see §7).
- **Not a replacement.** Hub never writes back to Canvas or Workday. Every item links out to where the student acts on it.

What realistic integration looks like with what UBC gives students today:

| Source | How we get it | Why |
|---|---|---|
| Canvas | The student's own Personal Access Token → REST API; the **.ics calendar feed** as a fallback | The only official API a student can reach themselves |
| Workday | The student uploads the **View My Courses** Excel export | API access needs UBC CIO approval, which isn't realistic for us |
| Bookstore | Anonymous GETs on the textbook lookup plus Shopify `products.json` | Public, no login |
| Gradescope, iClicker, WeBWorK, PrairieLearn | **Through Canvas**: their grades and due dates usually land in the Canvas gradebook or calendar via LTI | No student-accessible API |
| Piazza, Ed, others | Later, per-source adapters (Ed has personal tokens; Piazza has none) | Instructor-dependent |
| UBCGrades, UBCExplorer, RateMyProfessors | Later: course-selection season only | Not part of "this week" |

**Scraping policy:** we scrape only public, logged-out pages (the Bookstore). We never scrape behind CWL.

## 2. Core user flows

### 1. First run (under 2 minutes)

1. Open Hub and go to Setup.
2. Upload the Workday .xlsx. Hub shows "Found 5 courses: CPSC 121 101, …".
3. Paste the Canvas token, or the Calendar Feed URL for no-token mode.
4. Hub looks up textbooks for each section automatically.
5. Land on the dashboard.

### 2. Morning check-in: "What's due today?"

- The dashboard opens on **Today / This week**.
- It shows one list sorted by due date, with a badge per source.
- Overdue and due-in-48h items are pinned to the top.
- Each row has a single tap-out link to Canvas (or wherever the item lives).

### 3. Week planner

- A 7-day view shows class times from the Workday schedule, with Canvas assignments and events overlaid.
- Heavy days, 3+ items, are flagged.
- Clashes in the Workday schedule (overlapping sections, exam conflicts) show as a warning banner.

### 4. Start of term: "What do I need to buy?"

- The Textbooks tab lists every required and recommended book across the student's sections.
- Each book shows the new, used and digital price, and a store link where the ISBN matches.
- The tab totals the required spend.

### 5. Notification triage (later phase)

- One feed for Canvas announcements (Phase 1).
- Piazza, Ed and Gradescope release notices come in when those adapters exist.

### 6. Course-selection season (later phase)

- Search a course and see UBCGrades distributions, UBCExplorer prerequisites and seat info together.
- Out of scope for the hackathon.

## 3. System architecture

**Decision: Python + Streamlit, one repo, one process.**

Why:
- **One language** for a team with two first-years.
- Streamlit turns plain Python into a web UI, with no JavaScript, build step or separate API server.
- **The server-side fetch comes free.** Canvas and the Bookstore both block cross-origin browser calls (CORS), so a pure frontend couldn't call them anyway. Streamlit runs Python on the server, so the calls just work.
- Mature libraries cover every source: `canvasapi`, `icalendar`, `openpyxl`, `requests`, `beautifulsoup4`.
- Mobile: Streamlit's layout is responsive enough for a demo. A native or PWA app is a Phase 3 question.

```
                ┌──────────────────────── Streamlit app (app.py) ─────────────────────────┐
 Browser ◄────► │  UI pages: Setup · This week · Courses · Textbooks                        │
                │        │                                                                  │
                │        ▼                                                                  │
                │  hub/logic.py   normalise · match course codes · dedupe · sort · clashes  │
                │        ▲                                                                  │
                │  hub/models.py  Course · Item · Textbook  (the shared model, §4)          │
                │        ▲                                                                  │
                │  adapters:                                                                │
                │   hub/canvas.py ──── HTTPS ───► canvas.ubc.ca /api/v1  (user's own token) │
                │   hub/ics.py    ──── HTTPS ───► Canvas/Moodle .ics feed URL               │
                │   hub/workday.py ◄── file upload (.xlsx)                                  │
                │   hub/bookstore.py ─ HTTPS ───► the.bookstore.ubc.ca, bookstore.ubc.ca     │
                │        │                                                                  │
                │  cache: st.cache_data (in-memory, TTL)                                    │
                └───────────────────────────────────────────────────────────────────────────┘
```

**Adapters.**
- Each source is one file with one public function that returns shared-model objects, e.g. `canvas.fetch(token) -> (list[Course], list[Item])`.
- Adapters know nothing about the UI, and the UI knows nothing about the sources.
- That split lets the four of us work in parallel against `fixtures/`.

**Auth strategy.**

| Option | Verdict |
|---|---|
| OAuth (Canvas developer key) | The right answer for a multi-user release. Needs UBC to issue a key plus a Privacy Impact Assessment through LT Hub. Phase 2. |
| Student's own token or feed URL, kept in the session only | **The MVP.** Allowed for single-user use of your own token. Never written to disk or logged. |
| Credential vault holding CWL passwords | **No.** It's a honeypot of UBC identities and a policy breach. |
| Session-cookie proxying of CWL | **No.** It breaks the moment CWL or Duo changes, and is the worst ToS and privacy exposure. |

**Sync, caching and failure handling.**
- Canvas and .ics data is cached for 15 min (`st.cache_data(ttl=900)`).
- Bookstore data is cached per term (`ttl=86400`), since textbook lists barely change.
- A manual "Refresh" button clears the cache.
- Canvas: follow `Link` pagination, back off on HTTP 429, and fetch sequentially rather than in parallel (see the throttling notes in api-standards.md).
- Scraper breakage: `bookstore.py` checks for the markers it expects. When they're missing, it returns `[]` and an "unavailable" status, and the UI shows "Textbooks unavailable right now". It never crashes the dashboard.
- Each source reports `ok | stale | error` to a small status strip on the Setup page.

## 4. Data model

**Decision:** three types, dataclasses in `hub/models.py`. Keep them small, and add fields only when a screen needs them.

```json
{
  "Course": {
    "key": "UBCV,2026W1,CPSC,CPSC121,101",
    "code": "CPSC 121",
    "section": "101",
    "term": "2026W1",
    "title": "Models of Computation",
    "grade": 84.5,
    "schedule": [{"day": "Mon", "start": "10:00", "end": "11:00", "room": "DMP 110"}],
    "sources": ["workday", "canvas"]
  },
  "Item": {
    "id": "canvas:assignment:123456",
    "course_key": "UBCV,2026W1,CPSC,CPSC121,101",
    "kind": "assignment",
    "title": "Problem Set 3",
    "due": "2026-10-02T23:59:00-07:00",
    "url": "https://canvas.ubc.ca/courses/1/assignments/123456",
    "source": "canvas",
    "done": false
  },
  "Textbook": {
    "course_key": "UBCV,2026W1,CPSC,CPSC121,101",
    "title": "Discrete Mathematics with Applications, 5/E",
    "isbn": "9781337694193",
    "required": true,
    "price_new": 302.88,
    "price_digital": 84.91,
    "store_url": null
  }
}
```

**Field rules:**
- **`kind`** is one of `assignment | quiz | exam | event | announcement`.
- **`course_key`** is the join key. It is the Bookstore/Workday section key, because it's the most specific. Canvas course names get mapped onto it by `logic.normalise_course_code()` (Sam's work), e.g. `"CPSC 121 101 2026W1"` becomes `"UBCV,2026W1,CPSC,CPSC121,101"`.
- **`Item.id`** is `source:type:upstream_id`. Dedupe uses it, plus a (course, title, due) match when the same assignment arrives from both the API and the .ics feed.
- **Times** are ISO 8601 with a timezone offset. Convert to `America/Vancouver` for display only.

## 5. Screens

1. **Setup / Integrations**
   - One card per source (Workday upload, Canvas token or .ics URL, Bookstore automatic).
   - Each card shows its status (ok, stale or error) and when it last synced.
   - One sentence per card on what we read and that nothing is stored.
2. **This week (dashboard, the default)**
   - Header: today's date plus a count ("4 due this week, 1 overdue").
   - List grouped by day. Each row shows the source badge, course code, title and due time, and links out.
   - Overdue items are red, and due-in-48h items amber.
   - Streamlit sidebar: course filter chips.
3. **Week calendar**
   - Seven columns: class blocks from Workday, with deadlines overlaid as markers.
   - A clash warning banner when there's a clash.
4. **Course detail**
   - Code, section, instructor, schedule and current Canvas grade.
   - Upcoming items for the course, its textbooks, and links to its Canvas page.
5. **Textbooks**
   - A table across all courses: title, ISBN, required?, new, digital, store link.
   - A total for required items.
6. **Announcements feed (Phase 1 stretch)**
   - Canvas announcements for all courses, newest first, with an "unread since last visit" marker.

## 6. MVP vs full vision

| Phase | Scope | Needs |
|---|---|---|
| **0: Hackathon (now)** | Workday .xlsx import, Canvas PAT and .ics, Bookstore textbooks, the This week / Courses / Textbooks / Setup screens | Nothing from UBC |
| **1: Polish** | Week calendar, clash detection, announcements feed, Moodle .ics (for UBCO or other schools), Ed personal token | Nothing from UBC |
| **2: Multi-user** | Hosted deployment, Canvas OAuth developer key, accounts, encrypted per-user settings | UBC LT Hub: developer key and PIA |
| **3: Full vision** | Course-selection search (UBCGrades, UBCExplorer), notifications and push, PWA or mobile app, official UBC endorsement, deeper Workday data (UBC API via the CIO's Integration Enablement Centre) | UBC partnership |

## 7. Risks and constraints

- **UBC IT policy.**
  - Anything that uses UBC identity data at scale needs a Privacy Impact Assessment through LT Hub.
  - UBC enterprise API access goes through the Office of the CIO and requires meeting policies SC14 and SC3.
  - The MVP avoids both: each student uses their own data on their own session.
- **Privacy (FIPPA).**
  - UBC is a public BC body, so any official deployment falls under FIPPA, including its data-residency expectations.
  - The MVP stores nothing server-side: tokens live in the Streamlit session and vanish when it closes.
  - Rules: never log tokens or feed URLs, never commit them, and never put them in URLs we generate.
- **ToS and rate limits.**
  - Canvas policy forbids collecting other users' PATs. That's fine for a single-user demo, and it's why Phase 2 needs OAuth.
  - Bookstore: robots.txt allows product pages, and checkout is for humans only (we never touch the cart). We haven't read the textbook site's Terms of Use yet; do that before any public launch.
  - Throttle every scraper and cache per term.
- **Fragility.** The Bookstore HTML and the Workday export format can change without notice. Mitigate with defensive parsers, one fixture file per format in `fixtures/`, and a test that fails loudly.
- **Maintainer bus factor.** UBCGrades and UBCExplorer survive as alumni side projects, which is the known failure mode. Mitigations:
  - Plain Python with few dependencies.
  - Adapters isolated so one breaking doesn't take down the app.
  - This doc plus AGENTS.md, so a new contributor or their coding agent can pick it up.
  - Two first-year maintainers: this is a feature, since they're here for 3+ more years.

## 8. Differentiation

Past attempts fall short in three ways:
- **Browser extensions** break with every DOM change and only run on one browser.
- **Notion templates** are manual copying.
- **Scraper scripts** need a terminal and die with their author.

Hub wins if it does three things well:

1. **Joins data rather than just listing it.** No existing tool connects *your Workday sections* to *your Canvas deadlines* to *your textbooks* by section. The shared `course_key` is the product.
2. **Is faster than opening Canvas.** The dashboard has to load in under 2 s from cache and answer "what's due" in one glance, or the habit never forms.
3. **Is honest about sources.** Every item says where it came from and links there. The status strip shows when a source is stale. Students trust a tool that admits a gap more than one that silently misses a deadline.
