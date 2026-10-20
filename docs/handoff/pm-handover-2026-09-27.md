# PM handover: 2026-09-27 (after HelloHacks)

Written by Terrace's Claude Code session (PM / regent) at the end of the weekend. Read AGENTS.md first; it's still binding.

## Where things stand

- **Live site:** https://hello-hacks26-terraceonhigh.vercel.app, deployed from `main` at `036eaa9`. `main` is now `56eaa29` after the README merged. That change is docs only, so no redeploy is needed.
- **Deploys** run only when someone triggers the workflow by hand: `gh workflow run ci.yml --ref main`.
- **Result:** Lauds was submitted to HelloHacks 2026 and didn't reach the top 3 of 24.
- **Brand:** Lauds, with accent `#b84028`. The code still uses `hub/`, `~/.ubc-hub/` and the `gather-*` keys, on purpose.

## Merged this weekend (highlights)

| PR | What |
|---|---|
| #99 / #100 | Zero-click demo through the real adapters; honest mode; Canvas feed link moved into an httpOnly cookie |
| #101 | Rebrand from UBC Hub to Lauds, with the burnt-orange accent |
| #104 / #109 | Sync with Jacky's fork (standalone sync CLI); URLs point at the team site |
| #106 | Live link in the README and GitHub Deployments |
| #107 | Full-semester demo student: 195 records → 76 items, 9 sources |
| #110 | Chain-link deep links with the URL on hover; gear Settings button |
| #112 | Workday **Download .ics** with reminders (parity with ubc-workday-ics) |
| #105 / #108 | Pitch deck source, plus layout and fact fixes |
| #115 | README rewrite with diagrams |

## Open: needs a decision or an owner

- **#114, LICENSE all rights reserved (Terrace's call).** Check the names: Devpost lists "Samaya Lidder". This PR's LICENSE says "Sam Lidder", which is wrong and needs fixing. After it merges, the README's `LICENSE` link works.
- **#111, pitch kit (docs only):** speaker notes, the .pptx export, and `JUDGE-CHEATSHEET.md`. The canonical deck is Jacky's Claude Design canvas.
- **#88 (Sam):** WeBWorK and Brightspace connect. Conflicts are resolved, but it's blocked on real-account screenshots (rule 9) and on Jacky's decision about `db.merge_course_into` and fuzzy matching.
- **#103 (Piazza feed):** clean, but it returns its own `Post` type outside the shared model, which is Jacky's call. It has nothing that uses it and no live proof yet.
- **#60–64, #70, #77–79, #96:** Vihaan's and Jacky's adapter PRs. Each needs a conflict fix, a decision (#70 adds the paid `anthropic` dependency), or live proof.
- **Close:** #81 (comms channel, never merge), #87, #20, #21 and #34, all superseded.

## Known gaps (see JUDGE-CHEATSHEET.md for full wording)

1. **The cross-source merge** ("the same quiz shows once") only runs in the demo pipeline, as an exact match. The real store dedupes on `(source, url)`.
2. **The extension sends captures, including grades,** through a stateless Vercel function (US region, no privacy review).
3. **Urgency** comes from a keyword heuristic, not machine learning.
4. **The hosted synced store (Neon) is off**, returning 503. There are no real users yet.
5. **Workday imports in the web app aren't saved:** they're lost on reload. The quick fix is `localStorage`.

## Running it locally

- **Demo** (full semester, port 8080): `uv run python tools/local-demo.py` next to `next start` on :3000. See the script's docstring.
- **Real data** (Canvas/PrairieLearn login windows): `bash tools/real-data.sh`, then open http://localhost:3000. Use `localhost`, not 127.0.0.1.

## Lessons for next time

- **The Devpost page is part of the product.** Every special prize required a 1-minute demo video, and we had none. Our page had no live link and a placeholder page address.
- **Judging came in two stages.** Small 3-judge panels picked the finalists; a 5-judge panel only ranked those. Optimise for the first stage: the "why" first, a working demo, a clear new-user path, and a live link.
- **The technical rubric rewards** custom logic, *one* explained challenge, fitting tools, and saying which parts you built versus reused or AI-generated.
- **A strong Q&A answer** names a real risk, a concrete experiment, and the result that would change direction.

## Next: StormHacks 2026 (Oct 3–4, SFU Burnaby)

- **Judge-model work is on humboldt**, in podman container `judge-model`, folder `/root/judge-model`.
  - Files: `BRIEF.md`, `stormhacks-2026-judge-model.md`, `TASK.md`, and `REPORT.md` when done.
  - An async Claude session runs there in tmux window `work`; Remote Control runs in tmux window `rc`.
  - Devpost's terms forbid scraping, so the data stays private and small.
  - The container isn't set to restart after a reboot.
- **Check progress:** `ssh humboldt 'podman exec judge-model git -C /root/judge-model log --oneline'`
