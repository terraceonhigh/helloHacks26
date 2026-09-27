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
| Blackboard Learn REST | App key plus admin-added integration; 3-legged OAuth [docs](https://docs.blackboard.com/rest-apis/learn/getting-started/basic-authentication) | No |
| D2L Brightspace | Admin registers the app, then OAuth2 auth code [docs](https://docs.valence.desire2learn.com/basic/oauth2.html) | No |
| Google Classroom | OAuth2 with `classroom.courses.readonly` and `classroom.coursework.me.readonly` [docs](https://developers.google.com/workspace/classroom/guides/auth) | Yes |
| MS Graph Education | Delegated `EduAssignments.ReadBasic` | Likely needs admin consent **[unverified]** |
| Ed Discussion | Personal API token; undocumented API ([edapi](https://pypi.org/project/edapi/)) | Yes |
| Piazza | No official API; unofficial login-based client ([piazza-api](https://github.com/hfaran/piazza-api)) | Fragile |
| Gradescope / iClicker | LTI only; grades flow into the Canvas gradebook ([iClicker @ UBC](https://lthub.ubc.ca/2023/04/21/improvement-to-how-iclicker-cloud-works-with-canvas/)) | Read them via Canvas |
| PrairieLearn | No student-facing API. Own CWL-backed login (same flow the browser-login adapters already use for Canvas), then the per-course-instance "assessments" page lists each assessment with a due date. **[page markup unverified — nobody on the team has pulled up a real UBC PrairieLearn course instance to confirm the HTML/route shape yet]** | Via our own browser-session adapter (`hub/site.py`), same pattern as Canvas — once someone verifies the page |
| Pearson MyLab & Mastering (incl. "MyMathLab") | No public developer API — closed-source, no docs beyond marketing/support pages. Reached either via LTI launch from the LMS (Canvas/Moodle/Brightspace/...) with LMS single sign-on, or a separate direct pearson.com login with a course access code; which one a course uses is an instructor setting we can't know in advance. **[login path cited below; page structure genuinely unknown, not just unverified]** | Not built — `hub/mymathlab.py` stops at `login()`; `fetch()` is an honest `([], [])` stub until someone with a real account can supply a sample page |
| Kaltura | Kaltura Session from a partner secret or appToken [docs](https://developer.kaltura.com/api-docs/VPaaS-API-Getting-Started/Kaltura_API_Authentication_and_Security.html) | No |

### Pearson MyLab & Mastering detail ("MyMathLab" is now one branded product inside this suite)

Researched 2026-09-26, same rigor as this file's header ("unmarked claims checked against the linked source; **[unverified]** = secondary or assumed"). MyLab/Mastering is closed-source with no public developer documentation, so confidence here is markedly lower than the WeBWorK/PrairieLearn-style rows above.

- **Cited, real sources:**
  - LMS single sign-on and LTI certification: "With single sign-on through your Learning Management System into Pearson, students are ready on their first day," and Pearson states it's LTI Certified, supporting "LTI 1.3 / LTI Advantage" and "LTI 1.1 Legacy Integration" for Canvas, Blackboard, Brightspace by D2L, Moodle, Schoology and Sakai. Pearson also states it does not store institutional data beyond anonymized user IDs and course IDs for grade sync. [LMS integration services](https://www.pearson.com/en-us/higher-education/educators/digital-learning-platforms/lms-integration-services.html)
  - A separate, non-LTI direct-login path also exists today, keyed to a course/access code rather than the LMS: [registration.mypearson.com](https://registration.mypearson.com/), [mylabprograms.pearson.com](https://mylabprograms.pearson.com/)
  - "MyMathLab" is the legacy name for one subject product now folded into the umbrella "MyLab and Mastering series" of 70+ subject products. [Wikipedia: MyMathLab](https://en.wikipedia.org/wiki/MyMathLab)
  - No public API found: searching for a MyLab developer API surfaces only [github.com/pearsonapi](https://github.com/pearsonapi) (no MyLab-specific client) and Pearson's own marketing/support pages. **[unverified beyond "nothing found"]**
- **[secondary, weaker]:** a search-engine snippet of a third-party-hosted copy of Pearson's own accessibility user guide states screen readers "can read the Calendar, Results, Announcements, Study Plan topics, and list of available assignments" — the PDF itself couldn't be machine-read for this PR, so treat this as naming real UI sections, not a confirmed structure. [Pearson Accessibility User Guide (PDF, third-party mirror)](https://ysu.edu/sites/default/files/mathematics-achievement-center/Pearson%20Accessibility%20User%20Guide.pdf)
- **Genuinely unknown (not merely unverified):** the real post-launch URL/route shape of a student's assignment list; whether it's server-rendered HTML (scrapeable like PrairieLearn) or a JS SPA backed by unversioned XHR; whether a saved-session cookie survives being revisited outside a fresh LTI launch (hub.site's whole "reuse a saved session" model assumes this); due-date field format; and a stable per-assignment URL for hub.db's `UNIQUE(source, url)` key. None of these should be guessed at — see `hub/mymathlab.py`'s module docstring for what a human with a real account needs to check first.
