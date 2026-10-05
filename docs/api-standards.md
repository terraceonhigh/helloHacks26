# API standards: integration targets

Researched 2026-09-26. **This is a research snapshot, not how we build.** The team went with browser-session login instead of PATs/`canvasapi` (UBC no longer issues student PATs); see AGENTS.md and `hub/`. Unmarked claims were checked against the linked source. **[unverified]** means it came from a secondary source or was assumed.

## TL;DR: what a student can use without UBC IT

| Target | Use this | Needs admin? |
|---|---|---|
| Canvas | Personal access token (PAT) → REST `/api/v1`; calendar ICS feed as the no-token mode | No for a demo; OAuth dev key for a multi-user release |
| Workday Student | User uploads the "View My Courses" Excel export | API access = UBC CIO approval, not realistic |
| UBC Bookstore (textbooks) | Anonymous GET on `the.bookstore.ubc.ca/CourseSearch` (HTML) | No |
| UBC Bookstore (store) | Shopify `bookstore.ubc.ca/products.json` | No |
| Moodle (other schools) | `token.php` + `moodle_mobile_app` → REST web services; iCal export | Usually no (mobile WS on by default over HTTPS) |
| Google Classroom | OAuth user consent | No, unless the Workspace admin blocks it |
| Ed Discussion | Personal API token (undocumented API) | No |

**Architecture suggestion:** iCalendar feeds are the base layer (Canvas and Moodle both expose one, and one parser covers both). Put per-source adapters behind one internal model: `Course`, `Section`, `Assignment`, `Event`, `Grade`, `Textbook`. Leave LTI 1.3 for later.

---

## Canvas (canvas.ubc.ca)

- **Style:** REST/JSON at `https://canvas.ubc.ca/api/v1/`, with `v1` as the only version. GraphQL at `POST /api/graphql` (Relay pagination, explorer at `/graphiql`) is not feature-complete. [GraphQL](https://canvas.instructure.com/doc/api/file.graphql.html)
  - The docs are moving to developerdocs.instructure.com.
- **Auth:**
  - **PAT:** create one at Account → Settings → Approved Integrations → New Access Token.
    - ⚠ Canvas API Policy forbids an app from collecting other users' PATs. Multi-user apps **must** use OAuth. [OAuth](https://canvas.instructure.com/doc/api/file.oauth.html)
    - For the demo, each teammate uses their own PAT.
  - **OAuth2:** needs an admin-issued developer key. Access tokens last 1 h and come with a refresh token.
  - **LTI 1.3:** needs an admin to register the tool, and is instructor-oriented. [Tools](https://canvas.instructure.com/doc/api/file.tools_intro.html)
  - **UBC-specific:** anything using UBC identity data needs a Privacy Impact Assessment through LT Hub. [LT Hub](https://lthub.ubc.ca/initiatives/technology-pilots/request/), [UBC Canvas API community](https://open.ubc.ca/ubc-canvas-api-user-community/)
- **Endpoints for a student dashboard:**

  | Need | Path |
  |---|---|
  | Everything upcoming (best single feed) | `GET /planner/items?start_date=&end_date=` ([planner](https://canvas.instructure.com/doc/api/planner.html)) |
  | Courses + current grade | `GET /courses?include[]=total_scores&include[]=term` ([courses](https://canvas.instructure.com/doc/api/courses.html)) |
  | To-do / upcoming / missing | `GET /users/self/todo`, `/users/self/upcoming_events`, `/users/:id/missing_submissions` ([users](https://canvas.instructure.com/doc/api/users.html)) |
  | Calendar | `GET /calendar_events?type=assignment&context_codes[]=course_N` (max 10 contexts per call) ([calendar](https://canvas.instructure.com/doc/api/calendar_events.html)) |
  | Announcements | `GET /announcements?context_codes[]=course_N` (param required) ([announcements](https://canvas.instructure.com/doc/api/announcements.html)) |
  | Assignments, submissions, modules, files, inbox **[unverified paths]** | `/courses/:id/assignments?include[]=submission`, `/courses/:id/students/submissions?student_ids[]=self`, `/courses/:id/modules?include[]=items`, `/courses/:id/files`, `/conversations` |

- **Pagination:**
  - Default page size is 10; set `per_page` for more.
  - Follow the `Link` header (`next`/`last`, and `last` may be missing). [pagination](https://canvas.instructure.com/doc/api/file.pagination.html)
- **Throttling:**
  - Each token has its own leaky bucket. Responses carry the `X-Request-Cost` and `X-Rate-Limit-Remaining` headers.
  - A throttled request returns 429, so back off and retry.
  - Parallel requests pay an up-front cost, so prefer sequential calls. [throttling](https://canvas.instructure.com/doc/api/file.throttling.html)
- **ICS fallback:**
  - Each user has a personal feed under Calendar → "Calendar Feed". It includes events and assignments but not To-Do items. [guide](https://community.canvaslms.com/t5/Student-Guide/How-do-I-view-the-Calendar-iCal-feed-to-subscribe-to-an-external/ta-p/331)
  - The URL contains a secret, so treat it like a token.
- **SDK:** `pip install canvasapi` (UCF Open, not Instructure). [repo](https://github.com/ucfopen/canvasapi). UBC examples: [ubccapico/canvas_api_examples](https://github.com/ubccapico/canvas_api_examples).
- **Admin-only, so treat as unavailable:** Canvas Data 2 / DAP and Live Events. [DAP](https://developerdocs.instructure.com/services/dap)

## Workday Student (UBC)

- UBC went live on Workday Student on **2024-05-21**, replacing the SSC. [UBC Science](https://science.ubc.ca/students/blog/workday) **[secondary]**
- **API standards (tenant-side):**
  - **SOAP (Workday Web Services):** versioned WSDLs, currently v47.0 (2026R2). Student services: `Student_Records`, `Student_Core`, `Academic_Foundation`, `Student_Finance`, etc. [directory](https://community.workday.com/sites/default/files/file-hosting/productionapi/index.html)
  - **REST:** `https://{host}/ccx/api/v1/{tenant}/{resource}`, using OAuth 2.0 via "Register API Client for Integration" plus an Integration System User. **[secondary]**
  - **RaaS:** Advanced custom reports exposed at `/ccx/service/customreport2/{tenant}/{owner}/{report}?format=json`, with no pagination. **[secondary]** [Workato docs](https://docs.workato.com/connectors/workday/workday_raas.html)
  - Extend, Prism and WQL are admin/tenant tools. **[unverified]**
- **Student access:**
  - There's no self-serve developer portal. API access is requested through the UBC Office of the CIO (ServiceNow "Request API Access" plus a Qualtrics data access form). You must meet policies SC14/SC3; contact edg@ubc.ca. [CIO](https://cio.ubc.ca/data-governance/data-governance-services/access-ubc-data)
  - Not realistic within a hackathon.
- **What works:**
  - Academics → Registration & Courses → **View My Courses** → Excel export. The user uploads it, and we parse it into section keys.
  - Prior art for .xlsx→.ics: [ubc-workday2cal](https://github.com/jackkoskie/ubc-workday2cal), [workdaycal.vercel.app](https://workdaycal.vercel.app/). **[the exact export button path is unverified]**
- **Public section data:** courses.students.ubc.ca now redirects to Workday (CWL). The Bookstore's course lookup (below) is the best public list of sections and instructors.

## UBC Bookstore

- **Store: `bookstore.ubc.ca` runs on Shopify** (header `powered-by: Shopify`).
  - `GET /products.json?limit=N` returns public product JSON.
  - robots.txt allows products but disallows `/cart`, `/checkout`, `/account` and `/admin`. Checkout is for humans only. [robots.txt](https://bookstore.ubc.ca/robots.txt)
  - A Storefront API token is **[unverified]**.
- **Textbook lookup: `the.bookstore.ubc.ca`** runs a separate PHP "eSolution" platform (vendor unknown). All of these are anonymous GET requests:
  - Terms: `/Course/term?campus=UBCV` (or `UBCO`)
  - Departments: `/Course/program?campus=UBCV&term=2026W1`
  - Sections: `/Course/course?campus=UBCV&term=2026W1&program=CPSC` returns keys like `UBCV,2026W1,CPSC,CPSC121,101`
  - Materials: `/CourseSearch/?source=course&course[]=UBCV,2026W1,CPSC,CPSC121,101` returns HTML with the instructor, required/recommended, title, author, ISBN, and new/used/digital prices.
  - Many sections show "No course materials are currently listed".
  - There's no real robots.txt, and we haven't read the site's Terms of Use yet. Rate-limit requests and cache per term.
- **Join:** Workday export → section key → CourseSearch → ISBN → Shopify product / digital (VitalSource / Campus eBookstore).

## Moodle (LMS-agnostic support)

- **Protocols:** REST (XML or JSON), SOAP and XML-RPC. [client guide](https://docs.moodle.org/dev/Creating_a_web_service_client)
- **Token:** `GET /login/token.php?username=&password=&service=moodle_mobile_app`
- **Call:** `/webservice/rest/server.php?wstoken=&wsfunction=&moodlewsrestformat=json` (the default format is XML).
- **Student functions:** [function list](https://docs.moodle.org/dev/Web_service_API_functions)
  - `core_webservice_get_site_info` (returns the user id)
  - `core_enrol_get_users_courses`
  - `core_calendar_get_action_events_by_timesort`
  - `mod_assign_get_assignments`
  - `gradereport_user_get_grade_items`
  - `core_course_get_contents`
- **Admin setup:** mobile web services are on by default for HTTPS sites. [mobile WS](https://docs.moodle.org/en/Mobile_web_services)
- **iCal:** `calendar/export_execute.php?userid=&authtoken=&preset_what=all&preset_time=recentupcoming`. [calendar](https://docs.moodle.org/405/en/Using_Calendar)

## 1EdTech and other standards

| Standard | Purpose | Useful to a student app? |
|---|---|---|
| **LTI 1.3 / Advantage** | OIDC launch plus signed JWT; AGS (grades), NRPS (roster), Deep Linking. [security](https://www.imsglobal.org/spec/security/v1p0/), [LTI](https://www.1edtech.org/standards/lti) | Only when embedded in an LMS, and it needs admin registration. This is the post-hackathon path. |
| **OneRoster 1.2** | SIS↔LMS rostering and gradebook (REST/CSV, OAuth2 client credentials) [spec](https://www.1edtech.org/standards/oneroster) | No (system-to-system) |
| **Caliper** | Learning-analytics events [spec](https://www.1edtech.org/standards/caliper) | No |
| **Common Cartridge / Thin CC** | Moving course content between LMSs | No |
| **QTI 3.0** | Assessment interchange | No |
| **CLR 2.0 / Open Badges 3.0** | Verifiable achievement credentials (W3C VC) [spec](https://www.1edtech.org/standards/clr) | Maybe, for showing badges or transcripts a student already holds |
| **xAPI / cmi5** | Statements sent to a Learning Record Store [xAPI](https://xapi.com/overview/) | Rare; it needs the institution's LRS |

### Other platforms

| System | Auth | Can a student self-serve? |
|---|---|---|
| Blackboard Learn REST | App key plus admin-added integration; 3-legged OAuth [docs](https://docs.blackboard.com/rest-apis/learn/getting-started/basic-authentication) | No |
| D2L Brightspace | A plain logged-in browser session reaches real, working JSON endpoints for the student's own identity and course enrollments -- see detail below. The official Valence developer-key/OAuth program is a separate, heavier path still needed for anything beyond that. | Partially -- see detail |
| Google Classroom | OAuth2 with `classroom.courses.readonly` and `classroom.coursework.me.readonly` [docs](https://developers.google.com/workspace/classroom/guides/auth) | Yes |
| MS Graph Education | Delegated `EduAssignments.ReadBasic` | Likely needs admin consent **[unverified]** |
| Ed Discussion | Personal API token; undocumented API ([edapi](https://pypi.org/project/edapi/)) | Yes |
| Piazza | No official API; unofficial login-based client ([piazza-api](https://github.com/hfaran/piazza-api)) | Fragile |
| Gradescope / iClicker | LTI only; grades flow into the Canvas gradebook ([iClicker @ UBC](https://lthub.ubc.ca/2023/04/21/improvement-to-how-iclicker-cloud-works-with-canvas/)) | Read them via Canvas |
| PrairieLearn | No student-facing API. Own CWL-backed login (same flow the browser-login adapters already use for Canvas), then the per-course-instance "assessments" page lists each assessment with a due date. **[page markup unverified — nobody on the team has pulled up a real UBC PrairieLearn course instance to confirm the HTML/route shape yet]** | Via our own browser-session adapter (`hub/site.py`), same pattern as Canvas — once someone verifies the page |
| WeBWorK | **Verified 2026-09-26 against a real UBC course** (MATH_V 100A ALL SECTIONS 2026W1, `webwork.elearning.ubc.ca`). No student-facing API — it's a legacy Perl-rendered app, no JSON anywhere. At UBC, this deployment isn't reached via a standalone WeBWorK login at all: the session is established by launching the course's "WeBWorK" link from Brightspace (LTI SSO); once that cookie exists, plain GETs to the course URL work fine on their own, no relaunch needed. The Assignments page is `<li data-set-status="open"\|"not-open"\|"past-due">` items (not a table): only an *open* set's status line ("Open. Due October 1, 2026, 11:59:00 PM PDT.") carries a real due date — a not-yet-open set only shows when it opens, and a past-due set's "Answers available for review[ on ...]" date is when *answers* unlock, not the original due date. No score/grade shows anywhere on this page (a separate Grades page exists, not yet explored). Also confirmed separately: WeBWorK sets *are* embedded in this same course's Canvas-equivalent (Brightspace) as an LTI "WeBWorK" tool link, but their due dates are typed in by hand on that side and can drift from WeBWorK's own. `hub/webwork.py` is a small standalone browser-session adapter (`hub/site.py`'s login/session core) that reads WeBWorK's own due dates for that drift-correction case, and for schools that run WeBWorK standalone with no LMS in front of it at all. | Via our own browser-session adapter (`hub/site.py`) — verified |
| Kaltura | Kaltura Session from a partner secret or appToken [docs](https://developer.kaltura.com/api-docs/VPaaS-API-Getting-Started/Kaltura_API_Authentication_and_Security.html) | No |

## Ed Discussion (edstem.org) detail

Implemented in `hub/ed_discussion.py`. The table row above cites the PyPI
listing; this section cites the **actual `edapi` source**, cloned and read
directly (`git clone https://github.com/smartspot2/edapi`, maintainer
`smartspot2` — this is the real, maintained Ed Discussion client; there is
also an `edapi-fork` on PyPI, not used here), not just its description.

- **Auth:** a personal API token the student creates themselves at
  https://edstem.org/us/settings/api-tokens (the exact URL `edapi`'s own
  `AUTH_MESSAGE` constant points a user to), sent as
  `Authorization: Bearer <token>` (`edapi/edapi.py`'s `EdAPI._auth_header`).
  No OAuth, no admin step — same self-serve shape as a Canvas PAT.
- **API base:** `https://us.edstem.org/api/` (`edapi/edapi.py`'s
  `API_BASE_URL`). The student-facing web app is a different host,
  `https://edstem.org/us/...` (confirmed by e.g. Yale's help page:
  "Ed Discussion site URLs should look similar to:
  https://edstem.org/us/courses/1234/discussion/" —
  https://help.canvas.yale.edu/a/1544915).
- **My courses:** `GET /api/user` (`EdAPI.get_user_info()`) returns
  `courses: [{course: {id, code, name, year, session, status}, role, lab}]`
  (`edapi/types/api_types/endpoints/user.py`, `.../course.py`) — real,
  confirmed by reading the type definitions field-by-field.
- **Threads:** `GET /api/courses/<course_id>/threads`
  (`EdAPI.list_threads()`) returns threads shaped per
  `edapi/types/api_types/thread.py`'s `API_Thread`: `id` (global post
  number), `course_id`, `number`, `type` (`"post"` / `"question"` /
  `"announcement"`, per `edapi/constants.py`'s `ThreadType`), `title`,
  `content`/`document` (free-text body), `category`/`subcategory` (an
  instructor-defined discussion category, e.g. "Assignment 1" — **not** a
  date or a deadline classification), `is_pinned`/`pinned_at`,
  `created_at`/`updated_at` (post timestamps).
- **No due-date-shaped field exists anywhere on a thread.** The full
  `API_Thread` type was read top to bottom; there is no `due`, `deadline`,
  or `date` field. This confirms the TL;DR table's "Ed Discussion:
  undocumented API" entry in a specific, checkable way: it isn't merely
  undocumented, its real (if unofficial) type shapes genuinely carry no
  date. `hub/ed_discussion.py` therefore surfaces pinned/announcement
  threads as **undated** `Item`s (`due=None`) — real courses, and a real
  "this is more than an ordinary post" signal, but never an invented date.
- **Per-thread web URL:** reasoned, not confirmed by `edapi` (it never
  builds one — it only calls the API). `hub/ed_discussion.py` uses
  `https://edstem.org/us/courses/<course_id>/discussion/<thread_id>`, by
  analogy to the one confirmed web URL shape above. Flagged here as the
  one inferred piece; it doesn't risk a `hub.db` `(source, url)` collision
  either way, since `thread["id"]` is documented as unique across all of
  Ed, not just within one course.

### D2L Brightspace, detail (requested outside the normal issue-tracked roadmap, 2026-09-26)

**Not a tracked target for UBC** in the sense of having its own issue (compare: WeBWorK #23, Macmillan Achieve #24, Moodle #25) -- but it turned out one real course this project has access to runs partly through Brightspace, so the section below is **verified live** (Terrace, 2026-09-26), not a guess from public docs the way the first draft was.

- **A logged-in browser session reaches real JSON, no developer key needed:**
  - `GET /d2l/api/lp/unstable/users/whoami` -- confirms who's logged in.
  - `GET /d2l/api/lp/1.50/enrollments/myenrollments/?orgUnitTypeId=3&isActive=true&canAccess=true` -- the student's own active course enrollments, with a course code/name/homepage URL per course. Paginated via a `PagingInfo.Bookmark`/`HasMoreItems` cursor; the one real account checked has only one active enrollment (`HasMoreItems: false`), so a second page was never actually seen, but `hub/brightspace.py` follows the cursor regardless since D2L documents it as their standard paging convention.
  - Both returned clean, ordinary JSON to a plain authenticated GET -- no OAuth flow, no admin-issued key, same session-cookie pattern the Canvas adapter already uses in this project. `hub/brightspace.py` uses these two calls for `Course`s.
- **Due dates/calendar events: no JSON source found.** The Calendar screens (both the course homepage's widget and the full Calendar tool's Agenda/List views) are built from an older format meant for Brightspace's own page rendering, not for other programs to read directly -- and no separate, documented JSON endpoint for calendar/due-date data turned up while testing. Per this project's rule for logged-in sites (read JSON, not page HTML), `hub/brightspace.py` does not scrape those Calendar screens; it returns courses only, with an empty item list, rather than guess. Whether a real due-dates JSON endpoint exists elsewhere, or an HTML-scrape exception should be granted here (the way PrairieLearn and WeBWorK have one, since neither has any JSON API at all), is a decision for Jacky/the team, not something this file resolves on its own.
- **Multi-tenant**, confirmed by the URL shape itself: this course lives at `ubc.brightspace.com` on an institution-specific path, not a shared host the way `canvas.ubc.ca` is for Canvas -- `hub/brightspace.py` takes the instance base URL as a parameter, never a constant.
- **Course URLs use an "Org Unit Number"**: `/d2l/home/<orgUnitId>` is a course's homepage -- confirmed live (matches the enrollment JSON's own `HomeUrl` field).
- **The official Valence developer-key/OAuth2 program** (`docs.valence.desire2learn.com`) is still the only *documented, admin-sanctioned* integration path, same blocker Workday has -- separate from, and heavier than, the plain-session JSON access confirmed above. That program would be the right path for anything beyond a single student's own read-only data (e.g. a multi-user deployment), matching this project's existing Canvas OAuth phase-2 plan.
