# AGENTS.md: UBC Hub (helloHacks26)

Standing instructions for any coding agent (Claude Code, Codex, Copilot, Cursor…) working in this repo. Read this file fully before doing anything.

## What we're building

UBC Hub is a read-only dashboard that answers "what do I need to do this week?" by combining a student's Canvas, Workday and UBC Bookstore data.

- **[docs/design.md](docs/design.md)** covers the what and why: scope, architecture, data model, screens and phases. Stay inside **Phase 0** unless a human says otherwise.
- **[docs/api-standards.md](docs/api-standards.md)** has every endpoint, auth rule and source. Check it before guessing at an API.
- **GitHub issues** are the task list. Each person works from the issues assigned to them.

Stack: **Python 3.12 + Streamlit**, managed with **uv**.

## Who you might be working with

This team mixes experience levels. Pitch your help to the person, not the task.

| Person | GitHub | Experience | Owns | Branch |
|---|---|---|---|---|
| Terrace | `terraceonhigh` | 3rd year | Admin, repo owner, reviews | `terrace` |
| Jacky | `Random-Alpaca` | 3rd year | Canvas adapter (#1), README on `main`, reviews | `jacky` |
| Sam | `SamLidder` | 1st year, brand new to GitHub | Core logic (#2) | `sam` |
| Vihaan | `itsvihaanshah` | 1st year, just met Homebrew | Exploration tasks (#3 tracker, #4-#11) | `vihaan` |

**When working with Sam or Vihaan:**
- Treat it as teaching. Explain each terminal command in one plain sentence before running it, and say what "success" looks like.
- Prefer having them type or run things themselves when they want to learn. Don't silently do the whole issue.
- Take small steps: one function, run it, see the output, commit. Do not generate 300 lines at once.
- Explain git as you go: what `add`, `commit`, `push` and `pull` do, and why we use branches.
- If something breaks, show how to read the error before fixing it.
- Never run destructive git commands (`reset --hard`, `push --force`, `clean -fd`, `branch -D`) for them. If one seems needed, stop and tell them to ask Jacky or Terrace.

**When working with Jacky or Terrace:** normal senior pace, less explanation.

## First-time setup (macOS)

Explain each step to the human; don't just run them all.

```bash
# 1. Homebrew: the macOS package installer (skip if `brew --version` works)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. git, GitHub CLI and uv (uv installs Python and our libraries for you)
brew install git gh uv

# 3. Log in to GitHub from the terminal (opens a browser, choose HTTPS)
gh auth login

# 4. Get the code and switch to your own branch (replace <your-branch>: sam, vihaan, jacky, terrace)
gh repo clone terraceonhigh/helloHacks26
cd helloHacks26
git switch <your-branch>

# 5. Install Python + dependencies (first run takes a minute)
uv sync

# 6. Run the app: it opens at http://localhost:8501
uv run streamlit run app.py
```

If step 6 shows "UBC Hub … your setup works", you're done. Windows users: install uv from https://docs.astral.sh/uv/ and use the same `uv` commands.

## Daily workflow

```bash
git switch <your-branch>
git pull                           # get your branch's latest
git fetch
git merge origin/main              # bring in everyone else's merged work
# ...work...
uv run pytest                      # run tests before committing
git add <files you changed>
git commit -m "Short description of what you did"
git push
```

When an issue is done, open a PR from your branch into `main` (`gh pr create`) and ask Jacky or Terrace to review. Mention the issue with `Closes #N` in the PR description.

## Rules that protect the repo

1. **Work on your own branch.** Don't commit directly to `main`.
2. **README.md on `main` belongs to Jacky** while they're writing it. Don't edit it on any branch, or you'll cause merge conflicts. Put notes in `docs/` instead.
3. **Never commit secrets.** Canvas tokens and Canvas/Moodle `.ics` feed URLs are passwords.
   - Keep them in `.env` or `.streamlit/secrets.toml`; both are gitignored.
   - In the app, keep them in `st.session_state` only.
   - Never print, log, or put them in a URL.
   - The repo is **public**. If a secret gets committed, tell Terrace immediately and revoke it in Canvas. Deleting the commit is not enough.
4. **Only use your own data.** Canvas API policy forbids collecting other people's tokens. Test with your own token or with `fixtures/`.
5. **Be polite to the Bookstore.** Only public, logged-out pages. Cache per term, and never hammer it in a loop. Never touch cart, checkout or account pages.
6. **Never scrape anything behind CWL login.**

## Code layout and conventions

```
app.py              Streamlit entry point (UI only, no fetching or parsing logic here)
hub/models.py       Course, Item, Textbook dataclasses: the shared model (docs/design.md §4)
hub/logic.py        normalise, match course codes, dedupe, sort, clashes (pure functions)
hub/canvas.py       Canvas REST adapter
hub/ics.py          .ics feed adapter
hub/workday.py      Workday .xlsx import
hub/bookstore.py    Bookstore textbook lookup + Shopify product match
fixtures/           sample JSON/.xlsx/.ics/.html for tests and UI work (fake data only)
tests/test_*.py     pytest tests
```

- **Everything speaks the shared model.** Each adapter has one public function that returns `Course`, `Item` or `Textbook` objects. The UI and logic never see raw API JSON or HTML.
- **Create files when your issue needs them.** Don't scaffold the whole layout up front.
- **Keep it plain.** Use functions and dataclasses; avoid class hierarchies, frameworks-on-frameworks and new dependencies without asking the team. Add dependencies with `uv add <package>`, never `pip install`.
- **Handle failure without crashing the dashboard.** When a source breaks, return `[]` plus an error status; the UI shows "unavailable".
- **Test the logic.** Each parser or piece of logic gets at least one small pytest test against a fixture. Adapters that hit the network are tested against saved fixtures, not live sites.
- **Times** are timezone-aware `datetime`s. Display in `America/Vancouver`.
- **Fixtures must be fake or anonymised.** No real student numbers, names or tokens.
