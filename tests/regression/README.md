# UI regression oracle

`check_ui_regression.py` checks that a candidate UI (the Figma rewrite, a branch, a
hosted URL) behaves like the demo baseline, tag `demo-2026-09-27`. It's opt-in:
plain `uv run pytest` doesn't collect it.

```bash
uv run playwright install chromium                                        # once
uv run python tests/regression/check_ui_regression.py --candidate origin/sam           # a git ref
uv run python tests/regression/check_ui_regression.py --candidate ../figma-export      # a dir (web/ or repo root)
uv run python tests/regression/check_ui_regression.py --candidate https://x.figma.site # a URL
#   --baseline REF|DIR|URL   (default demo-2026-09-27)
#   --mode auto|local|sample --out SCREENSHOT_DIR --keep-logs
#   --tab-alias All=Overview,Tasks=Assignments,Deadlines=Calendar   (the default; '' for none)
```

**Redesigns.** Each baseline tab is looked up by its own label, then by its
`--tab-alias` (the default covers the "Gather" nav from PR #45). A baseline tab
with no counterpart is a FAIL (`Tab missing: Materials`) and the run carries on.
Rows come from table rows, else list items holding a link, else the container
of each item's "Open" link, read from its text (course code, a parseable date,
an urgency word, a bare lowercase kind, the title). A field the baseline shows
and the candidate's rows don't (e.g. Kind) is a `Row fields shown` FAIL, and the
rest is compared without it. A Sample toggle that defaults ON in local mode is
a FAIL, then it's switched OFF so the fixture comparison still runs. Missing
controls or elements are findings, never timeouts: element waits cap at 30s.

**Modes.** In local mode (the default when both sides are Next.js apps it can serve)
it builds a fixture `hub.db` from fake rows, runs this checkout's `hub.api` on it
(CORS origin patched to the harness's port), and serves each side with `next dev`
and `NEXT_PUBLIC_HUB_API`. When the candidate can't be pointed at `hub.api` (a
URL, a Vite/static export) both sides run in Sample mode. The browser clock and
`hub.api`'s clock are frozen at one instant, so both renders see the same urgency,
status and sample due dates. A git ref's `web/` is extracted to
`$TMPDIR/hub-ui-regression/<sha>/web` and `npm ci`'d once.

**Behaviour (FAIL on any difference from the baseline).** Per tab: row set, order,
Urgency text (case-sensitive), Due instant (parsed, so date format may change),
deep-link hrefs, done items never shown, Hide overdue on/off, Show next 5/10. Also
tabs present (including Courses: codes, title/term/grade, per-course rows and
Urgency), Show next/Hide overdue controls, Sample toggle presence and default,
and Connect Canvas/PrairieLearn buttons present with a visible accessible label
(never clicked). Everything is found by accessible role, name or text
(`get_by_role`, `get_by_label`, header text), never CSS classes, so new markup
passes as long as it behaves the same.

**Visual (WARN only).** Full-page screenshots at desktop 1280, tablet 768 and
375px, light and dark, saved to `--out`; horizontal scroll per width;
button-label contrast (computed colour against the composited background, WCAG
4.5). The baseline's white-on-white Connect buttons in the dark scheme are
labelled as a known baseline defect. The baseline also scrolls horizontally
at 375px.

Exit code 1 on any FAIL. Needs local port binding (so not inside a network
sandbox), and registry access on the first run for each ref.
