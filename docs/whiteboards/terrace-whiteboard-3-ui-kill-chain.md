# Terrace's paper notes #3: the UI sketch, a homework kill chain (transcribed)

Hand-drawn during HelloHacks 2026 (26–27 Sep), transcribed on 2026-09-28.
It's philosophy, and the whiteboard owns it. Unclear words are marked [?].
Earlier notes: `docs/handoff/terrace-whiteboard-2026-09-26{,-b}.md` on `main`
("the human is the subagent; the pane is the prompt list; a row is a prompt").

## The sketch (three panes, left to right)

**Left: a collapsible sidebar, "Connections:"**
- [Canvas]
- [Moodle]
- [Yada yada], meaning every other platform
- etc.

**Centre: the task table, headed "N tasks today"**

| course | MMDD | link to hw, needed readings & files (scrape) | link to Canvas submit |
|---|---|---|---|
| foo 100 | ↘ | ↘ | ↘ |
| barr 200 | ↘ | ↘ | ↘ |
| fizz 300 | ↘ | ↘ | ↘ |

- MMDD is the due date. An arrow and the word "array?" suggest sorting by it.
- Each ↘ is a jump: the readings/files cell opens the right pane, and the
  submit cell deep-links to the platform's own submission page.

**Right: a collapsible sidebar, "Just a clone of Finder tbh"**
- Folders: **Class Notes**, **Readings**, and a template **.docx**.
- An arrow back to the readings column: "**Scrape these from the course
  connected. LLM agent or heuristic fetch?**"

## Read as a kill chain (find, fix, track, target, engage, assess)

| Step | In the sketch | In `lauds` |
|---|---|---|
| Find | Connections sidebar | `lauds login`, `lauds sync` |
| Fix | "N tasks today" | `lauds today` |
| Track | MMDD, sorted | `lauds due --week`, `lauds status` |
| Target | readings/files cell and the Finder pane | `lauds show <id>` and the item's folder |
| Engage | "link to Canvas submit" | the item's deep link |
| Assess | the row leaves the table | `done`, then the next `sync` |

## The open question, answered (proposal, 2026-09-28)

**Heuristic first, LLM second.**
1. **Heuristic (in the adapters):** gather what the platform already links to
   the item: the files attached to the assignment, links in its description,
   its module's pages and files, and the matching week of the syllabus. These
   go into `Item.files` (`ItemFile`: name, url, kind).
2. **LLM (the concierge's school-prep skill, not this repo):** only for what
   the heuristics can't do:
   - matching readings to tasks when the prof didn't link them (the "PrairieLearn
     was only at the bottom of the syllabus" pain point);
   - writing the one-page brief for each item;
   - pre-filling the template `.docx` with its heading and prompt, never the work.
3. **The Finder clone is a real folder:** `<school dir>/<course>/<item>/` with
   `Readings/`, `Class Notes/`, the template, and a link to the submit page.
