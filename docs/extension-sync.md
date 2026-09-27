# Browser extension sync (Issue #82)

This is the single-user, installed-browser path. The extension core handles
tab selection, scheduled capture, local storage, and eventual Vercel upload
for every registered provider. Each provider supplies its own capture file.
The verified capture today reads Canvas JSON in a tab where the student has
signed in, selects only fields required by `hub.canvas.parse_capture()`, and
keeps that capture in extension-local storage.
It never reads a CWL password or copies an LMS cookie, token, or calendar-feed
URL to Vercel.

## Try local capture

1. In Chromium, open `chrome://extensions`, enable Developer mode, and load
   `extension/` as an unpacked extension.
2. Sign in to `https://canvas.ubc.ca` yourself in a normal tab.
3. Open the **Lauds Sync** popup, select Canvas, and press **Sync selected provider**. The
   popup reports whether capture and Vercel normalization succeeded. If no Canvas tab is open, it
   opens one; sign in there and press Sync again.

The `/api/normalize` route must be deployed before the Vercel step can pass.
Until then, a failed normalization still leaves the sanitized capture in
extension-local storage; the popup reports the HTTP failure.

The extension also attempts a capture for each registered provider every 30
minutes while Chrome and an already-open provider tab are available. It POSTs
the capture to Vercel's stateless `/api/normalize`, which calls the provider's
existing Python adapter and returns shared-model rows with `stored: false`.
Captures and normalized rows stay in `chrome.storage.local` under
`latestCaptures` and `latestModels`, keyed by provider, with access limited to
trusted extension contexts. They are removed when the extension is removed.

## Provider coverage

| Provider | Extension capture | Reason |
| --- | --- | --- |
| Canvas | Implemented, fixture-tested; live account verification pending | JSON endpoints and shared-model mapper are already in `hub/canvas.py` |
| Moodle | Experimental on `jacky-extension-providers-exp`; synthetic tests only | Uses page JS session key with same-origin AJAX JSON, then existing adapter mapping. The proposed AJAX methods are not confirmed on a real school site |
| Blackboard | Experimental on `jacky-extension-providers-exp`; courses only | Its draft REST path and session-cookie access are unverified; no task endpoint identified |
| Piazza | Experimental on `jacky-extension-providers-exp`; pinned/staff posts only | JSON RPC shape is based on its draft adapter, without a live account check or due dates |
| Google Classroom, Ed | Pending | Google Classroom's draft uses OAuth; Ed's draft uses a personal API token. The current browser-session capture does not implement either flow |
| PrairieLearn | Experimental on `jacky-extension-providers-exp`; browser navigation and parser tests only | Opens the signed-in home page, visits each course assessments page, selects row fields in the tab, then reuses `hub/prairielearn.py` mapping. PM approved only a narrower current-page DOM read; automated navigation needs Terrace's further review |
| Brightspace | Pending | No existing adapter in this checkout; official OAuth app registration needs an institution-side decision |
| WeBWorK | Usually via Canvas | Issue #23 tracks verifying Canvas External Tool assignments; direct set-date correction has no permitted JSON capture yet |
| Workday | Separate hosted import | The existing site imports the student's Excel export in the browser |
| Bookstore, key dates | No extension needed | Public/static sources can be fetched without a student login |

Adding a verified provider means providing its browser capture, registering
its origin and script in `extension/providers.js`, adding a narrow manifest
host permission, and implementing `parse_capture()` inside the provider's
existing `hub/<provider>.py` adapter. `hub.captures.parse()` dispatches to that
adapter; the extension transport does not branch on the provider name. A
registry entry without a working capture and parser is not considered support.

The experimental branch uses `optional_host_permissions` for Moodle and
Blackboard. The student supplies the HTTPS site origin and grants access for
that origin in Chrome. This is intended for a manual test; no unverified
provider is enabled in the stable PR #84.

PrairieLearn runs only when the student presses Sync: the extension opens its
home page in an existing signed-in tab and navigates that tab through each
course's assessments page. A scheduled sync never moves the tab. Only course
titles, assessment titles, group labels, first full-credit end text, score
text, status, and safe same-origin links leave the tab. The browser never
sends raw page HTML or the full popover HTML. The implementation is held in
the experimental PR until Terrace reviews the broader navigation flow. The
PM agent approved a PrairieLearn-only exception for reading a single page the
student is already viewing, but explicitly excluded crawling. This branch
implements Jacky's later request to navigate across course assessment lists;
it never opens an individual assessment or quiz link.

## Hosted upload contract

The extension is prepared to POST normalized rows to
`https://hello-hacks26.vercel.app/api/sync` with a Lauds-specific bearer key set
in its popup. That key is distinct from all LMS credentials. The upload route
and durable hosted database are **not deployed yet**. Do not put a key in the
extension until the route, key provisioning, and store exist. Without a key,
the popup accurately says the capture is local only.

The eventual endpoint must authenticate the upload, cap the request at 1 MB,
validate the shared-model rows, and upsert by `(source, url)` into
private durable storage. Dashboard reads need separate authentication. A
serverless SQLite file is not durable on Vercel.

Terrace's PM agent reported on PR #81 that no hosted database is known to be
connected and that choosing/provisioning one is held for Terrace. This
installed extension does not close the no-download goal in Issue #76.

## Tests

`node --test extension/*.test.mjs` checks capture minimization, same-origin
pagination, another provider's dispatch, the Vercel upload request, and
local-only behavior without a key.
`uv run pytest tests/test_web_normalize.py tests/test_captures.py
tests/test_canvas.py` checks the Vercel route and server-side mapping into the
shared model. None of these tests needs a live LMS account.
