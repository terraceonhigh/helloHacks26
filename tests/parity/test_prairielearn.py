"""Parity-to-superset for the PrairieLearn adapter: every golden under
tests/oracle/prairielearn/ replayed through lauds.adapters.prairielearn.

The goldens don't carry machine-readable call parameters for every case (only
`parse_capture` and `live_selfhost`'s `extra` are fully self-describing) - the
other two replay recipes below mirror exactly what
tools/harvest_oracle.py called main with (same fixtures, same order, same
per-call course/group/campus params), documented in each golden's own
"extra"."note" text. New golden files fail loudly (see the else-branch)
rather than silently skipping, so a future golden can't go unchecked.
"""
import json

import pytest
from bs4 import BeautifulSoup

from lauds.adapters import prairielearn as pl
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

CASES = golden_paths("prairielearn")
PL_BASE = "https://us.prairielearn.com"


def _row(html):
    return BeautifulSoup(html, "html.parser").find("tr")


def _replay_assessment_rows(inputs):
    # Exactly tools/harvest_oracle.py's 8 to_item() calls (see this golden's
    # "extra"."note" for what each covers), replayed through parse_row().
    calls = [
        ("prairielearn/open_row.html", "CPSC 317", "Programming Assignments",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/not_open_row.html", "CPSC 317", "Programming Assignments",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/closed_row.html", "CPSC 317", "Quizzes",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/closed_never_attempted_row.html", "CPSC 317", "Quizzes",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/open_row.html", "CPSC 317", "Practice for Quizzes",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/open_row.html", "CPSC 317", "Formal Quizzes (repeated for practice)",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/open_row_mst.html", "CPSC 317", "Programming Assignments",
         "prairielearn", PL_BASE, "221053"),
        ("prairielearn/open_row.html", "MECH 260", "Programming Assignments",
         "prairielearn_ok", "https://prairielearn.ok.ubc.ca", "221053"),
    ]
    items = [
        pl.parse_row(_row(inputs[path]), course_code=course_code, group=group,
                      campus_key=campus_key, base=base, ci_id=ci_id)
        for path, course_code, group, campus_key, base, ci_id in calls
    ]
    return {"items": items}


def _replay_course_title_parsing(inputs):
    titles = json.loads(inputs["prairielearn/course_titles.json"])
    courses = [pl.to_course(str(n), title) for n, title in enumerate(titles, start=1)]
    return {"courses": courses}


def _replay_parse_capture(inputs):
    capture = json.loads(inputs["prairielearn/parse_capture.json"])
    courses, items = pl.parse_capture(capture)
    return {"courses": courses, "items": items}


# URL path (relative to the golden's own "extra"."base") each live fixture
# was captured from - the naming convention tools/harvest_live.py's
# RecordingReq/_slug uses, cross-checked against the fixture's own content
# (live_00 is the home page; live_01 is course_instance/1's, the only course
# whose title matched COURSE_TITLE and so got its assessments fetched).
_LIVE_SELFHOST_PATHS = {
    "prairielearn/live_00_home.html": "/",
    "prairielearn/live_01_pl_course_instance_1_assessments.html": "/pl/course_instance/1/assessments",
}


class _FixtureResp:
    def __init__(self, text):
        self.status = 200
        self.ok = True
        self._text = text

    def text(self):
        return self._text


class _FixtureReq:
    """Replays a live golden's captured raw pages by URL, so `pl._run` runs
    unmodified over recorded fixtures instead of the network."""

    def __init__(self, base, inputs, path_of):
        self.base = base
        self.by_path = {}
        for rel, content in inputs.items():
            path = path_of.get(rel)
            if path is None:
                raise AssertionError(f"no known URL path for live fixture {rel!r}; "
                                     f"update _LIVE_SELFHOST_PATHS")
            self.by_path[path] = content

    def get(self, url):
        path = url[len(self.base):]
        if path not in self.by_path:
            raise AssertionError(f"unexpected request path {path!r} - fixture set is incomplete")
        return _FixtureResp(self.by_path[path])


def _replay_live_selfhost(golden, inputs):
    base = golden["extra"]["base"]
    campus_key = golden["extra"]["campus_key"]
    req = _FixtureReq(base, inputs, _LIVE_SELFHOST_PATHS)
    courses, items = pl._run(req, campus_key, base)
    return {"courses": courses, "items": items}


_REPLAYS = {
    "assessment_rows": lambda g, inputs: _replay_assessment_rows(inputs),
    "course_title_parsing": lambda g, inputs: _replay_course_title_parsing(inputs),
    "parse_capture": lambda g, inputs: _replay_parse_capture(inputs),
    "selfhost": _replay_live_selfhost,
}


@pytest.mark.parametrize("golden_path", CASES, ids=lambda p: p.stem)
def test_prairielearn_parity(golden_path):
    golden = load_golden(golden_path)
    case = golden["case"]
    replay = _REPLAYS.get(case)
    if replay is None:
        raise AssertionError(
            f"tests/oracle/prairielearn/{golden_path.name}: no parity replay wired up for "
            f"case {case!r} - add one to tests/parity/test_prairielearn.py's _REPLAYS")
    new = replay(golden, load_inputs(golden_path))
    assert_superset(golden_path, new)


def test_every_prairielearn_golden_has_a_replay():
    # Guards against a new golden silently going unchecked (golden_paths()
    # picks up new files automatically; this makes sure _REPLAYS keeps up).
    cases = {load_golden(p)["case"] for p in CASES}
    assert cases <= set(_REPLAYS)
