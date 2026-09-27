# API standards: integration targets

Researched 2026-09-26. Unmarked claims were checked against the linked source. **[unverified]** means it came from a secondary source or was assumed.

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
| Blackboard Learn REST | The *official* app-key/3-legged-OAuth program [docs](https://docs.blackboard.com/rest-apis/learn/getting-started/basic-authentication) still needs an admin, same as before -- but whether a plain logged-in session cookie also reaches Blackboard's own documented REST endpoints directly, the way Brightspace's did, is an untested hypothesis -- see detail below. | Unconfirmed hypothesis -- see detail |
| D2L Brightspace | Admin registers the app, then OAuth2 auth code [docs](https://docs.valence.desire2learn.com/basic/oauth2.html) | No |
| Google Classroom | OAuth2 with `classroom.courses.readonly` and `classroom.coursework.me.readonly` [docs](https://developers.google.com/workspace/classroom/guides/auth) | Yes |
| MS Graph Education | Delegated `EduAssignments.ReadBasic` | Likely needs admin consent **[unverified]** |
| Ed Discussion | Personal API token; undocumented API ([edapi](https://pypi.org/project/edapi/)) | Yes |
| Piazza | No official API; unofficial login-based client ([piazza-api](https://github.com/hfaran/piazza-api)) | Fragile |
| Gradescope / iClicker | LTI only; grades flow into the Canvas gradebook ([iClicker @ UBC](https://lthub.ubc.ca/2023/04/21/improvement-to-how-iclicker-cloud-works-with-canvas/)) | Read them via Canvas |
| PrairieLearn | No student-facing API. Own CWL-backed login (same flow the browser-login adapters already use for Canvas), then the per-course-instance "assessments" page lists each assessment with a due date. **[page markup unverified — nobody on the team has pulled up a real UBC PrairieLearn course instance to confirm the HTML/route shape yet]** | Via our own browser-session adapter (`hub/site.py`), same pattern as Canvas — once someone verifies the page |
| Kaltura | Kaltura Session from a partner secret or appToken [docs](https://developer.kaltura.com/api-docs/VPaaS-API-Getting-Started/Kaltura_API_Authentication_and_Security.html) | No |

### Blackboard Learn REST, detail (informed hypothesis only -- no live account, 2026-09-26)

**Not a tracked target for UBC** -- UBC runs Canvas, not Blackboard, and unlike Brightspace (one real course happens to also run through it, per hub/brightspace.py), there is no Blackboard instance or account anywhere on this project to check any of this against. Everything below is an **inference from Blackboard's own public developer documentation** (developer.blackboard.com / docs.blackboard.com/rest-apis/learn) plus the Brightspace precedent, **not a confirmed fact** the way the Brightspace detail section above is.

- **The reasoning, by analogy to Brightspace:** this project previously assumed Brightspace had no student self-serve path at all, because the only *documented, admin-sanctioned* integration is the Valence OAuth2 developer-key program. It turned out that assumption was too pessimistic -- a plain logged-in browser session reaches Brightspace's own `/d2l/api/lp/...` JSON directly, no developer key needed, because that's what its own Ultra-equivalent web UI actually calls. Blackboard Learn Ultra is architecturally the same shape (a React/Ultra SPA frontend backed by Blackboard's own documented REST API, `/learn/api/public/v1/...` and versioned siblings), so the same kind of session-cookie access is a *plausible* hypothesis here too -- but nobody has opened a real Blackboard Ultra course's Network tab to confirm it, the way Terrace did for Brightspace. Treat every claim below as "documented to exist, and plausibly session-cookie-reachable", not "known to work".
- **Documented resources this hypothesis rests on** (all cited from Blackboard's own REST API docs, not tested live):
  - `GET /learn/api/public/v1/users/me` -- a documented `me` alias for the calling user on the Users resource, mirroring Brightspace's `users/whoami`. Whether the literal `me` alias is honoured on the specific tenant/version this would run against is unconfirmed.
  - `GET /learn/api/public/v1/users/{userId}/courses` -- the documented Course Memberships resource: each membership carries the enrolled course's internal `courseId` (a primary key, not the human-readable code), paginated via Blackboard's own documented list shape (`{"results": [...], "paging": {"nextPage": "..."}}`).
  - `GET /learn/api/public/v1/courses/{courseId}?expand=term` -- the documented Courses resource, whose own `courseId` field (confusingly, a *different* field than the membership's `courseId` -- Blackboard's docs use `courseId` for the human-readable code here) gives the real course code, `name` gives the title, and `expand=term` is documented to embed the Term resource's `name` inline.
  - `hub/blackboard.py` implements exactly these three calls for `Course`s, tolerating a missing `term` or `courseId` rather than guessing (same defensive shape hub/brightspace.py and hub/prairielearn.py already use for their own "unexpected shape" gaps).
- **Due dates/calendar events: no confirmed JSON source, same honest gap as Brightspace.** Blackboard's docs do describe a `GET /learn/api/public/v1/calendars` resource, but every description of it is of *calendar objects* (a course calendar's id/name/type) -- not a feed of dated events or due items. No documented "list this course's upcoming due dates" endpoint was found in the v1/v2/v3 docs consulted. (The Gradebook Column resource does document a `grading.due` timestamp field, a *plausible* future source -- unconfirmed whether it's populated the way a dashboard would need, and a bigger design question than this file settles.) Per this project's rule for logged-in sites (read JSON, never page HTML) -- and per this same reasoning already applied to Brightspace -- `hub/blackboard.py` does not scrape Ultra's rendered HTML to fill this gap; it returns courses only, with an empty item list. Whether to chase the Gradebook due-date field, or to grant Ultra HTML an explicit scrape exception (the way PrairieLearn/WeBWorK have one, since neither has *any* JSON API at all, unlike here), is a decision for Jacky/the team, not something this file resolves on its own.
- **Multi-tenant** like Brightspace, not a single shared host the way `canvas.ubc.ca` is for Canvas -- `hub/blackboard.py` takes the instance base URL as a parameter, never a constant.
- **The official app-key/3-legged-OAuth2 program** (`docs.blackboard.com/rest-apis/learn/getting-started/basic-authentication`) remains the only *documented, admin-sanctioned* path for anything beyond the plain-session hypothesis above -- same blocker Workday has, and the same tier the Brightspace Valence program sits in relative to its own verified session-cookie finding.
