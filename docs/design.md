# Lauds: design spec

> **Code wins.** Where this doc and `main` disagree, the code on `main` and AGENTS.md (*Jacky's standard*) are right, and this doc is stale. Fix it here when you notice.

> **Palantir Gotham for students.** A provider-agnostic fusion layer: any number of information providers go into one shared model, and come out as one pane of glass. Canvas, Workday and the UBC Bookstore are the first three providers at UBC, not the product. Must extend to other ed-tech and other schools without touching the core. The binding version is the Mission section of [AGENTS.md](../AGENTS.md).

Answers Jacky's design prompt ([handoff/jacky-design-prompt.md](handoff/jacky-design-prompt.md)). The API facts behind every decision are in [api-standards.md](api-standards.md), with sources. This is the founding doc for the build. Where it says **Decision**, change it here first, then in code.

---

## 1. Product vision and scope

**Lauds is a read-only aggregator.** The student connects each source themselves; Lauds pulls from it, normalises the data, and shows one answer to "what do I need to do this week?"

- **Not a middleware or single sign-on layer.** We never hold CWL credentials. Proxying CWL sessions is the riskiest option legally and technically (see §7).
- **Not a replacement.** Lauds never writes back to Canvas or Workday. Every item links out to where the student acts on it.

What realistic integration looks like with what UBC gives students today:

| Source | How we get it | Why |
|---|---|---|
| Canvas | The student signs in themselves in a browser window Lauds opens (Playwright); Lauds reuses that session to read the same `/api/v1` JSON Canvas's own pages use. The **.ics calendar feed** as a fallback | UBC no longer lets students create Personal Access Tokens |
| Workday | The student uploads the **View My Courses** Excel export (schedule). **Billing and tuition due dates** are next, via a Workday export or statement upload **[unverified which export]** | API access needs UBC CIO approval, which isn't realistic for us |
| Bookstore | Anonymous GETs on the textbook lookup plus Shopify `products.json` | Public, no login |
| **Syllabus** | The student uploads the syllabus (PDF, DOCX or pasted text). An LLM extracts every dated item (exams, due dates, readings, *where* and *how* to submit) into Items, each with an excerpt from the syllabus as a citation | **Real pain point:** one prof never put due dates on Canvas, and the PrairieLearn deadlines were only at the bottom of the syllabus. Canvas isn't the source of truth, and the syllabus often is |
| UBC key dates | Public UBC academic calendar pages: add/drop, withdrawal, exam period, tuition due **[unverified URLs]** | Public, no login; the same for every student |
| PrairieLearn | **Built** (`hub/prairielearn.py`): the student's own browser session, then the course's assessments page | No student-facing API; same login pattern as Canvas via `hub/site.py` |
| Gradescope, iClicker, WeBWorK | **Through Canvas** when the instructor wires it up (LTI). Otherwise **through the syllabus** provider | No student-accessible API |
| Piazza, Ed, others | Later, per-source adapters (Ed has personal tokens; Piazza has none) | Instructor-dependent |
| UBCGrades, UBCExplorer, RateMyProfessors | Later: course-selection season only | Not part of "this week" |
| Lecture recordings and transcripts (Panopto, Kaltura) | Later, and only via official download buttons the student can already use | Behind CWL; see the scraping policy below |

**Output, not just input: an iCal export.** Lauds publishes one merged `.ics` file of every Item, which the student subscribes to from Apple, Google or Outlook Calendar. Most students already live in a calendar app. Lauds feeding it is the cheapest way to become the daily habit.

**Scraping policy:** we parse HTML only on public, logged-out pages (the Bookstore). Behind CWL we only read Canvas's JSON with the student's own session, never HTML, and we never see the CWL password.

### Prior art we're building on

These come from Terrace's own coursework tooling. We borrow the patterns; none of the personal course data is copied into this repo.
- **Per-course `syllabus.md` plus a deadlines `.ics`.** Grading tables, dated schedules and reading lists were hand-transcribed into Markdown, and each course got a generated `.ics` of deadlines. This is exactly what the Syllabus provider and the iCal export automate.
  - Lessons worth keeping: **stable UIDs** (`<course>-<item>@…`) with `SEQUENCE` bumps, so updates replace events instead of duplicating them. Put the **grade weight in the event title** ("Quiz 1 due (6.5% of final grade)"). Use two reminders (`VALARM` at −2 days and on the day).
- **Canvas grades snapshots.** A Canvas Grades page transcribed into a table (assignment, group, due, submitted, score, MISSING). It confirms which fields students actually check: missing-work status matters as much as due dates.
- **The `ics-from-appointments` agent skill.**
  - **Always produce something useful**: extract what's there and never refuse on partial data.
  - **Default the timezone** to `America/Vancouver` and note that it was assumed.
  - **Follow RFC 5545**: escaping and line folding.
  - **Dedupe** the same event arriving from two inputs.

  These same rules govern the Syllabus provider and the export. Use the `icalendar` library (already a dependency) rather than a hand-rolled writer.

## 2. Core user flows

### 1. First run (under 2 minutes)

1. Open Lauds and go to Setup.
2. Upload the Workday .xlsx. Lauds shows "Found 5 courses: CPSC 121 101, …".
3. Click "Connect Canvas" and sign in with CWL + Duo in the window that opens, or paste the Calendar Feed URL instead.
4. Lauds looks up textbooks for each section automatically.
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

### 4b. Syllabus drop: "What did Canvas miss?"

- Upload a syllabus. Lauds lists every dated item it found, each with the sentence it came from.
- New ones (not already in Canvas) are highlighted: "3 PrairieLearn deadlines found only in the syllabus".
- One click adds them to the dashboard and the iCal export.

### 5. Notification triage (later phase)

- One feed for Canvas announcements (Phase 1).
- Piazza, Ed and Gradescope release notices come in when those adapters exist.

### 6. Course-selection season (later phase)

- Search a course and see UBCGrades distributions, UBCExplorer prerequisites and seat info together.
- Out of scope for the hackathon.

## 3. System architecture

**Superseded 2026-09-26 (Terrace): the UI is Next.js in `web/`, deployed on Vercel. The backend stays Python.** The original reasoning below explains why Streamlit was the first pick. `app.py` survives as the frozen live-demo harness.

~~**Decision: Python + Streamlit, one repo, one process.**~~

Why:
- **One language** for a team with two first-years.
- Streamlit turns plain Python into a web UI, with no JavaScript, build step or separate API server.
- **The server-side fetch comes free.** Canvas and the Bookstore both block cross-origin browser calls (CORS), so a pure frontend couldn't call them anyway. Streamlit runs Python on the server, so the calls just work.
- Mature libraries cover every source: `playwright`, `icalendar`, `openpyxl`, `requests`, `beautifulsoup4`.
- Mobile: Streamlit's layout is responsive enough for a demo. A native or PWA app is a Phase 3 question.

```
                ┌──────────────────────── Streamlit app (app.py) ─────────────────────────┐
 Browser ◄────► │  UI pages: Setup · This week · Courses · Textbooks                        │
                │        │                                                                  │
                │        ▼                                                                  │
                │  hub/logic.py   normalise · match course codes · dedupe · sort (planned, #2)│
                │        ▲                                                                  │
                │  hub/db.py      SQLite ~/.ubc-hub/hub.db · save() · upcoming() · by_course│
                │        ▲                                                                  │
                │  hub/models.py  Course · Item · Textbook  (Jacky's; the contract)         │
                │        ▲                                                                  │
                │  adapters (built):                                                        │
                │   hub/canvas.py ──── HTTPS ───► canvas.ubc.ca /api/v1  (user's own session)│
                │   hub/prairielearn.py ─ HTTPS ─► PrairieLearn (user's own session)        │
                │   hub/ics.py    ──── HTTPS ───► Canvas/Moodle .ics feed URL               │
                │  adapters (planned): workday.py (.xlsx upload), bookstore.py (#20),       │
                │   syllabus.py (#17), ubc_dates.py (#19)                                   │
                │        │                                                                  │
                │  cache: st.cache_data (in-memory, TTL)                                    │
                └───────────────────────────────────────────────────────────────────────────┘
```

**Adapters.** Adding a provider (Moodle, Brightspace…) means adding one adapter file. The layout is owned by the backend (Jacky); `hub/site.py` is the shared core for sites the student logs into themselves.
- Each source is one file with one public function that returns shared-model objects, e.g. `canvas.fetch(start, end) -> (list[Course], list[Item])`.
- Adapters know nothing about the UI, and the UI knows nothing about the sources.
- That split lets the four of us work in parallel against `fixtures/`.

**Auth strategy.**

| Option | Verdict |
|---|---|
| OAuth (Canvas developer key) | The right answer for a multi-user release. Needs UBC to issue a key plus a Privacy Impact Assessment through LT Hub. Phase 2. |
| Student's own browser session or feed URL | **The MVP.** The student logs in themselves; the Canvas session is saved only on their machine at `~/.ubc-hub/canvas-state.json` (mode 600), never in the repo, never logged. |
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

**`hub/models.py` is the source of truth**, owned by the backend (Jacky). The JSON below is the **proposed** fuller shape, including the whiteboard fields. Additions go through Jacky. Keep the model small, and add fields only when a screen needs them.

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
- **`kind`** is one of `assignment | quiz | exam | reading | event | announcement | deadline | payment`. `deadline` covers admin dates like add/drop; `payment` covers tuition and fees.
- **Where, how and weight** (from the whiteboard: "how to do, what to do, where to access"). These are optional `Item` fields:
  - `platform`: where you do it (`"prairielearn"`, `"gradescope"`, `"canvas"`…), with `url` pointing there.
  - `how`: a one-line submission instruction.
  - `weight`: the share of the final grade, e.g. `0.065`.
  - `evidence`: for inferred Items, the syllabus sentence they came from, so the student can check it.
- **`course_key`** is the join key. It is the Bookstore/Workday section key, because it's the most specific. Canvas course names get mapped onto it by `logic.normalise_course_code()` (Sam's work), e.g. `"CPSC 121 101 2026W1"` becomes `"UBCV,2026W1,CPSC,CPSC121,101"`.
- **`Item.id`** is `source:type:upstream_id`. Dedupe uses it, plus a (course, title, due) match when the same assignment arrives from both the API and the .ics feed.
- **Times** are ISO 8601 with a timezone offset. Convert to `America/Vancouver` for display only.

### Pipeline and storage

**Providers → normalise to the shared model → store → rank → show the top N.**

**Storage (proposed by Terrace; Jacky decides):** one SQLite file.
- **Raw tables, one per provider** (`canvas_raw`, `bookstore_raw`, …), holding what each API returned. Re-normalise from these without refetching when a parser changes.
- **Normalised tables shared by all providers** (`courses`, `items`, `textbooks`), with a `source` column. The cross-source join happens here, so these are not split per provider.

### Ranking

**MVP: sort by due date.** Items with no due date go last and done items are hidden. This is `logic.sort_items()` in #2.

**Later: an urgency function** (jotted down, not built). It replaces the sort behind the same call, so the UI doesn't change:

```
if item.done:            exclude
if due < now:            overdue → pinned to the top, most overdue first
hours = max(due - now, 1 h)
urgency = (weight or 0.01) / hours     # 30% midterm in 3 days outranks a 1% quiz tomorrow
tiebreak: earlier due date
```

Open questions for when we build it:
- Should effort or length (e.g. an essay vs a quiz) count?
- Should an item that's already been submitted but isn't marked done sink?
- Should heavy days get a boost?
- Should the student be able to pin items?

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
| **0: Hackathon (now)** | Workday .xlsx import, Canvas via browser session and .ics, Bookstore textbooks, the This week / Courses / Textbooks / Setup screens | Nothing from UBC |
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

Lauds wins if it does three things well:

1. **Joins data rather than just listing it.** No existing tool connects *your Workday sections* to *your Canvas deadlines* to *your textbooks* by section. The shared `course_key` is the product.
2. **Is faster than opening Canvas.** The dashboard has to load in under 2 s from cache and answer "what's due" in one glance, or the habit never forms.
3. **Is honest about sources.** Every item says where it came from and links there. The status strip shows when a source is stale. Students trust a tool that admits a gap more than one that silently misses a deadline.
