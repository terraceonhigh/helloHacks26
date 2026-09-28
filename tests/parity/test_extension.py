"""Parity: every tests/oracle/extension/*.json golden (the browser-extension
capture goldens, hand-traced from extension/providers/*.js since node is
unavailable on this box - see each golden's own "extra.note").

Dispatches on the golden's own oracle_call/query text, same idea as
test_piazza.py's own extension-golden filter (which still owns the Piazza
case - see the canary at the bottom for why it isn't duplicated here):

- blackboard/moodle: the JS-side capture already matches
  parse_capture()'s own input shape 1:1 (BRIEF blocker finding's own
  replay confirmed this) - no normalisation code needed, just wiring.
- prairielearn's two cases DID have a real gap (the same blocker finding):
  extension/providers/prairielearn-index.js's dedupe/route-filter logic,
  and extension/background.js's merge of one capturePrairieLearnIndex()
  visit with each course's own capturePrairieLearnAssessments() page visit
  into parse_capture()'s {source, origin, courses} envelope. Both are now
  ported (lauds.adapters.prairielearn.capture_index_links/combine_capture).
"""
import json

import pytest

from lauds.adapters import blackboard, moodle, prairielearn
from tests.parity.superset import assert_superset, golden_paths, load_golden, load_inputs

ALL_EXTENSION_GOLDENS = golden_paths("extension")
_PIAZZA = {p for p in ALL_EXTENSION_GOLDENS if "hub.piazza" in (load_golden(p).get("oracle_call") or "")}
GOLDENS = [p for p in ALL_EXTENSION_GOLDENS if p not in _PIAZZA]

# The real extension flow for PrairieLearn (extension/background.js's
# captureNavigated()): visit the home page once (capturePrairieLearnIndex()),
# then each course's own assessments page (capturePrairieLearnAssessments()),
# merging {ci_id, title} with that page's {ci_id, assessments}. This golden's
# own "inputs" is only the assessments-page half (same as the real per-page
# capture); the index half is the same literal harvest_oracle.py used to
# build the golden - real, out-of-band knowledge a browser would actually
# have from the earlier home-page visit, not invented here.
_PL_ASSESSMENTS_ORIGIN = "https://us.prairielearn.com"
_PL_ASSESSMENTS_TITLE = "CPSC 317: Internet Computing, 2026 Winter Term 1"


def _dispatch(path):
    golden = load_golden(path)
    text = golden.get("oracle_call") or golden.get("query") or ""
    inputs = load_inputs(golden)
    if "hub.blackboard" in text:
        (raw,) = inputs.values()
        courses, items = blackboard.parse_capture(json.loads(raw))
        return golden, {"courses": courses, "items": items}
    if "hub.moodle" in text:
        (raw,) = inputs.values()
        courses, items = moodle.parse_capture(json.loads(raw))
        return golden, {"courses": courses, "items": items}
    if "capturePrairieLearnIndex" in text:
        (raw,) = inputs.values()
        anchors = json.loads(raw)
        return golden, {"courses": prairielearn.capture_index_links(anchors)}
    if "capturePrairieLearnAssessments" in text:
        (raw,) = inputs.values()
        page_capture = json.loads(raw)
        envelope = prairielearn.combine_capture(
            _PL_ASSESSMENTS_ORIGIN,
            [{"ci_id": page_capture["ci_id"], "title": _PL_ASSESSMENTS_TITLE}],
            [page_capture],
        )
        courses, items = prairielearn.parse_capture(envelope)
        return golden, {"courses": courses, "items": items}
    raise AssertionError(f"{path}: don't know how to dispatch oracle_call/query {text!r}")


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_extension_capture_is_a_superset(path):
    golden, new = _dispatch(path)
    assert_superset(golden, new)


def test_every_extension_golden_is_collected_somewhere():
    # Canary against a rename/move silently dropping a golden from both this
    # file's list and test_piazza.py's own filter (BRIEF blocker finding's
    # fix: "a canary asserting that every extension golden is collected").
    assert len(GOLDENS) + len(_PIAZZA) == len(ALL_EXTENSION_GOLDENS) == 5
    assert len(_PIAZZA) == 1
    assert len(GOLDENS) == 4
