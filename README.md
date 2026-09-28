# lauds (branch `lauds-cli`)

Lauds rebuilt as a CLI-first Python package: one command that pulls every
deadline, reading, textbook and class meeting from Canvas, PrairieLearn,
WeBWorK, Workday, the Bookstore and friends into one local SQLite file.

This is an **orphan branch**. `main` isn't its base; it's the spec and the
oracle. Every adapter here must reproduce main's output as a superset (see
[BRIEF.md](BRIEF.md), "The parity-to-superset rule"). Agents working on this
branch: read BRIEF.md first. It's binding.

## Layout

| path | what |
|---|---|
| `lauds/models.py` | shared records (Course, Item, ItemFile, Textbook, Meeting, Bundle), `status_of`, `category_for`, course-code canonicalising |
| `lauds/compat.py` | `to_main` / `bundle_to_main`: project lauds records onto main's shape |
| `lauds/adapters/` | one plugin module per provider (`NAME`, `fetch()`, optional `login()`, pure parse functions) |
| `lauds/session.py` | browser login, saved session (0600), pagination, 429 backoff |
| `lauds/store.py` | minimal SQLite store and the CLI's queries |
| `lauds/paths.py` | `~/.local/share/lauds/`, `~/.config/lauds/`, or `$LAUDS_HOME` |
| `tests/oracle/` | goldens harvested from main (never hand-edited) |
| `tests/fixtures/` | raw inputs the goldens were made from |
| `tests/parity/superset.py` | the comparator; `DIVERGENCES.md` lists the only allowed differences |

## Run the tests

```sh
export UV_PROJECT_ENVIRONMENT=/home/.venvs/lauds UV_LINK_MODE=copy
uv sync
timeout 600 uv run --no-sync pytest -q -p no:cacheprovider
```

Tests are network-free (`tests/unit`, `tests/parity`). Live checks against
the self-hosted servers live in `tests/live/` and aren't collected by pytest.

## A parity test, in full

```python
import pytest
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs
from lauds.adapters import webwork

@pytest.mark.parametrize("golden", golden_paths("webwork"), ids=lambda p: p.stem)
def test_webwork_parity(golden):
    g = load_golden(golden)
    raw = load_inputs(g)             # {"webwork/sets.html": "<html>...", ...}
    bundle = webwork.parse(raw, **g["extra"])
    assert_superset(golden, bundle)
```
