# Judge Q&A cheat sheet

Four adversarial judges (an investor, a security engineer, a UBC privacy officer and a skeptical student-designer) each asked their 10 hardest questions, checked against the code on `main` as of 2026-09-27. This page merges them. **Rule of thumb: admit the gap, say what's next, never overclaim.** Every answer below is under 40 words, so you can say it out loud.

## The five things that sink us if we overclaim

1. **"The same quiz shows up once" is demo-only.** The cross-source merge (`hub/logic.py` `dedupe()`) is an exact match on course, title and due time, and it only runs in the demo pipeline (`hub/demo.py`). The real store dedupes on `(source, url)`, which can never merge two sources. A fuzzy matcher exists (`suspected_duplicates()`) but isn't wired in.
2. **Data does leave the laptop.** The extension posts raw captures, including Canvas's current score, to the Vercel `/api/normalize` function. It's stateless and unlogged, but it's a server hop on US infrastructure with no region pinned and no privacy assessment.
3. **Urgency is a keyword rule, not ML.** What's on screen is `classify_urgency` in `hub/models.py`: a grade weight guessed from keywords ("final" 0.35, "quiz" 0.05), divided by hours left. The 72% classifier is an offline experiment on synthetic data, and nothing imports it.
4. **We have no users, no revenue model and no permission.** No UBC approval, no privacy impact assessment (PIA), no vendor terms review, and the Bookstore's Terms of Use haven't been read.
5. **A normal student can't get real data on the hosted site yet**, beyond pasting a Canvas calendar-feed link and importing a Workday .xlsx. Canvas login and PrairieLearn need a local install. The synced store is off (it returns 503).

## Say this, not that

| Don't say | Say instead |
| --- | --- |
| "Zero credential handling" | "No password handling. Session tokens stay on your laptop." |
| "Your data never leaves your laptop" | "Your password and session never leave your laptop." |
| "It intelligently merges the same assignment everywhere" | "Exact matches merge today; fuzzy matching is built and not wired in yet." |
| "ML-ranked" / "72% accurate" | "A transparent keyword-and-deadline heuristic." |
| "Failure never cascades" | "One provider failing can't take down the others." |
| "A new platform is one file" | "A new platform needs no change to the core model or logic." |
| "Subscribe on your phone" | "A calendar feed, served locally today; hosted is next." |
| "Closes the loop" (as if two-way) | "Opens it where it lives. Lauds is read-only." |
| "Real-time" / "always up to date" | "As fresh as the last sync; overdue flags recompute on every read." |
| "Compliant", "approved", "WCAG accessible" | "Not reviewed yet; here's what we'd do first." |
| "Students love it" / any user count | "We use it on our own accounts; user testing is next." |
| Comparisons to Palantir, military language | "Many narrow sensors, one fused picture." |

## Business (investor)

- **Who pays?** No business model yet; we proved the fusion layer first. The likely buyer is an institution or student-services group paying per student to cut missed deadlines. It's a hypothesis. *Don't:* invent freemium, ads, or "selling insights".
- **Why won't Canvas or UBC build it?** Canvas only sees Canvas. WeBWorK, PrairieLearn, Workday and the Bookstore never reach its To-Do, and a vendor won't rank a competitor. *Don't:* say Canvas "can't"; LTI tools overlap partly.
- **What's the moat?** Honestly, not a moat yet. One adapter is easy; keeping 14 alive plus cross-source matching is the hard part. Today our edge is speed and being the users. *Don't:* call 14 integrations a network effect (several are stubs).
- **Traction?** Just us, on real accounts in local mode. The hosted site runs on a demo student. *Don't:* count tests or demo items as traction.
- **Next 90 days?** Merge the in-review adapters, turn on the synced store, put it in front of 50 UBC students, and measure whether they open it on day 14. *(That's a target, not a plan already underway.)*
- **Who maintains it?** It's a real risk. The hedge: two first-years here three more years, isolated adapters, 325 tests. *Don't:* promise to go full-time.
- **Market size?** UBC is the test market. Moodle, Brightspace and Blackboard adapters point beyond it. We won't quote a TAM we can't defend.

## Product and fusion (student, security)

- **Why not Canvas To-Do plus calendar sync?** If everything's on Canvas, you don't need us. Lauds is for the student juggling five or more systems.
- **Does dedupe work on messy real data?** Only exact matches merge today, after course codes are normalised (`CPSC_V 110-101` becomes `CPSC 110`, which is real). "Quiz 3" vs "Quiz 3 (PL)" won't merge; the fuzzy detector isn't wired in.
- **How is urgency computed?** A keyword weight divided by hours until due, bucketed, then re-ranked by "what matters to you". It's transparent, not ML.
- **Wrong or stale data?** Overdue flags recompute on every read. Items are as fresh as the last sync, with no background refresh and no "last synced" shown yet. A broken source shows "unavailable"; nothing crashes.
- **Check it off: is it done in Canvas?** No. It's read-only, and a check-off is stored in this browser only.
- **Mobile?** No app. The plan is a calendar feed your phone subscribes to; today it's served locally. The class-schedule `.ics` download is in review (PR #112).
- **What does a hosted user get today?** Paste your Canvas feed link and import your Workday file, both handled in the browser. Everything else needs a local install for now.

## Security and engineering (security)

- **What credentials do you hold?** No passwords. Session cookies sit in a mode-600 file on the laptop (plaintext JSON, not encrypted). The sync key is kept only as a SHA-256 hash, and the feed link is an httpOnly cookie.
- **You read logged-in HTML?** Canvas and Moodle use their own JSON. PrairieLearn and WeBWorK have no student API, so we parse the page the student already sees, one request per course, backing off on 429. It's a documented exception; no ToS review yet.
- **What can the extension read?** Tabs on canvas.ubc.ca, piazza.com and us.prairielearn.com, plus sites the student grants one at a time. Captures go to our stateless normalize endpoint and back to the extension.
- **The origin check accepts any extension. Is that a CSRF hole?** Writes need a 43+ character bearer key; the origin check is defence in depth. Pinning our extension ID is the fix. Hosted sync is off, so it isn't exposed yet.
- **XSS?** React escapes all text, we never use `dangerouslySetInnerHTML`, the hosted sync accepts https URLs only, and feeds come from allowlisted Canvas hosts. There's no Content-Security-Policy yet.
- **A platform changes its HTML tomorrow?** That provider shows "unavailable" and saved items survive, but nothing alerts us. Inside one provider, one failing course aborts that run.
- **How many of the 325 tests hit real servers?** None, on purpose: they run on saved snapshots. Live checks against real UBC endpoints were manual, one at a time, and are documented in PRs.

## Privacy and policy (UBC privacy officer)

- **Is student data leaving Canada?** Yes, extension captures pass through Vercel, likely a US region. The call is stateless and unlogged, but it's still a disclosure. The fix is to normalise inside the extension or pin a Canadian region before real rollout.
- **The synced store holds grades on US servers?** It's off on purpose and returns 503. Turning it on needs a PIA through LT Hub and Canadian residency first.
- **Automating Canvas without an OAuth key?** One student reads their own data in their own session: the same JSON the Canvas web app loads. Multi-user needs a UBC developer key, and that's Phase 2.
- **Is the extension's auto-capture a bot?** Scheduled capture reads an already-open, signed-in tab. PrairieLearn's automated navigation is experimental and still in review for exactly this reason.
- **What if the laptop is stolen?** The attacker gets live session cookies until they expire, plus deadlines and grades. The files are permission-locked, not encrypted; the OS keychain is the next fix.
- **Why touch grades at all?** Fair challenge. Canvas's current score helps flag at-risk courses, but it's our most sensitive field. It's one optional field and easy to make opt-in or keep on the laptop.
- **The LLM syllabus reader?** It's a proposal, not merged. If it ships: opt-in per file, with what gets sent shown up front. Syllabi are the instructor's copyright.
- **Accessibility?** Partial: labels on inputs and buttons, and screen-reader-hidden icons. There's been no audit, and row links are labelled just "Open" (PR #110 improves that).
- **Liability for a missed deadline?** Canvas and the syllabus stay authoritative. Lauds links back to each item and says "unavailable" rather than pretending to be complete. We'd add that disclaimer in the UI.
- **Would UBC endorse it?** Not yet. That needs a PIA, an OAuth key and a UBC partner. The Bookstore is read from public pages only.

## Numbers you can defend

| Number | What it really is |
| --- | --- |
| 325 | Backend tests on saved snapshots, green in CI. No live calls. |
| 195 → 76 | Demo records fused into items; the demo fixtures are written to match. |
| 6 + 8 | Adapters merged + in review. Several in review are login-only. |
| 0 | Passwords seen or stored. **Not** zero credentials. |
| 72% | Offline classifier on synthetic data. **Not** what's on screen. |

## Deck lines to consider rewording (canvas owner's call)

- `rigor`: "Zero credential handling" → "No password handling". "Failure never cascades" → "One provider failing can't take down the others".
- `architecture`: "a calendar feed for your phone" is local-only today.
- `ooda` (loop): "Lauds closes the loop" can sound like two-way sync.
- Live demo: when you show Quiz 3, say "in the demo pipeline, exact matches merge".
