#!/usr/bin/env python3
"""Offline oracle harvest for the parity-to-superset rule (see BRIEF.md).

Regenerates every file under tests/fixtures/<adapter>/ (non-live_) and
tests/oracle/**/ (non-live_) from the oracle checkout (main,
/sdcard/Projects/helloHacks26 — READ ONLY, never imported for its side
effects beyond plain function calls, never written to). Nothing else writes
tests/oracle/.

Run it from the lauds-cli repo root, with the oracle's own venv (it has
requests/bs4/icalendar/openpyxl installed; nothing here touches the network):

    cd /sdcard/Projects/lauds-cli && \
    UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \
    timeout 300 /home/.venvs/hub-oracle/bin/python tools/harvest_oracle.py

Reproducibility: every fixture this script writes is either (a) a verbatim
copy of a real file from the oracle checkout, or (b) built here from fixed,
hardcoded literals (no randomness, no wall-clock reads) — running this
script twice produces byte-identical output (json.dumps(..., sort_keys=True)
plus stable insertion order from the oracle's own functions, which don't
themselves sort).
"""
import json
import re
import sys
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time as time_cls, timezone
from pathlib import Path

ORACLE_ROOT = "/sdcard/Projects/helloHacks26"
sys.path.insert(0, ORACLE_ROOT)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
ORACLE_OUT = REPO_ROOT / "tests" / "oracle"

from hub import (  # noqa: E402  (path insert must come first)
    bookstore, brightspace, canvas, captures, db, export_ics, ics,
    key_dates, models, moodle, prairielearn, webwork, workday, blackboard, piazza,
)
from hub.models import Course, Item, ItemFile, Meeting, Textbook, status_of  # noqa: E402

VAN = ics.VANCOUVER  # zoneinfo("America/Vancouver"), same object hub.ics uses

# ---------------------------------------------------------------------------
# JSON helpers: dataclasses.asdict()-shaped output, ISO-8601 dates/times,
# sorted keys (json.dumps(sort_keys=True) below handles key order; this only
# needs to turn non-JSON-native values into strings/lists).
# ---------------------------------------------------------------------------


def jsonable(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, set):
        return sorted(jsonable(v) for v in obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time_cls):
        return obj.isoformat()
    return obj


def records(courses=None, items=None, textbooks=None, meetings=None, **extra_lists):
    out = {}
    if courses is not None:
        out["courses"] = [jsonable(c) for c in courses]
    if items is not None:
        out["items"] = [jsonable(i) for i in items]
    if textbooks is not None:
        out["textbooks"] = [jsonable(t) for t in textbooks]
    if meetings is not None:
        out["meetings"] = [jsonable(m) for m in meetings]
    for k, v in extra_lists.items():
        out[k] = jsonable(v)
    return out


WRITTEN = []  # (kind, path) for the final report


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    WRITTEN.append(("golden", path))


def golden(adapter, case, inputs, oracle_call, output, now=None, extra=None):
    write_json(ORACLE_OUT / adapter / f"{case}.json", {
        "adapter": adapter,
        "case": case,
        "inputs": inputs,
        "oracle_call": oracle_call,
        "now": now,
        "extra": extra or {},
        "output": output,
    })


def result_golden(adapter, case, inputs, query, result, now=None, extra=None):
    """Like golden(), but for a call whose return value isn't a plain
    {courses, items, textbooks, meetings} record dump (tests/parity/
    superset.py's own contract: an "output" golden's top-level keys must be
    exactly a subset of RECORD_KEYS - anything else, e.g. hub.captures.
    normalize()'s extra 'source'/'stored' bookkeeping fields or
    hub.export_ics.to_ics()'s raw .ics text, goes under "result" instead,
    the same key tests/oracle/queries/*.json already uses for hub.db query
    goldens - superset.py's comparator already has a generic fallback path
    for exactly this shape)."""
    write_json(ORACLE_OUT / adapter / f"{case}.json", {
        "adapter": adapter,
        "case": case,
        "inputs": inputs,
        "query": query,
        "now": now,
        "extra": extra or {},
        "result": result,
    })


def fixture_text(adapter, name, content):
    path = FIXTURES / adapter / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    WRITTEN.append(("fixture", path))
    return f"{adapter}/{name}"


def fixture_json(adapter, name, obj):
    return fixture_text(adapter, name, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def fixture_copy(adapter, name, src_path):
    path = FIXTURES / adapter / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(Path(src_path).read_bytes())
    WRITTEN.append(("fixture", path))
    return f"{adapter}/{name}"


def fixture_bytes(adapter, name, content_bytes):
    path = FIXTURES / adapter / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content_bytes)
    WRITTEN.append(("fixture", path))
    return f"{adapter}/{name}"


def fixture_path(adapter, name):
    """Absolute path to an already-written fixture, for functions (openpyxl,
    BeautifulSoup) that want a real file/string rather than fixture text."""
    return FIXTURES / adapter / name


# ---------------------------------------------------------------------------
# canvas (hub/canvas.py) — pure mapping functions only; OAuth/token plumbing,
# host allowlisting and the browser-session path aren't record-shaped and are
# noted as out of scope in tests/oracle/INDEX.md.
# ---------------------------------------------------------------------------


def harvest_canvas():
    adapter = "canvas"

    # -- test_mapping / test_calendar_event_url_is_not_double_prefixed /
    #    test_announcement_has_no_due_date: one course, one of each kind. --
    raw_course = {"id": 7, "course_code": "CPSC 121", "name": "Models of Computation",
                  "term": {"name": "2026W1"}, "enrollments": [{"computed_current_score": 88.5}]}
    raw_quiz = {"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
                "plannable": {"title": "Quiz 2"}, "html_url": "/courses/7/quizzes/3"}
    raw_event = {"plannable_type": "calendar_event", "plannable": {"title": "Office hours"},
                 "html_url": "https://canvas.ubc.ca/calendar?event_id=9"}
    raw_discussion_default = {"plannable_type": "discussion_topic", "plannable": {"title": "Untitled discussion"}}
    raw_announcement = {"plannable_type": "announcement", "plannable_date": "2026-01-05T12:00:00Z",
                        "plannable": {"title": "Welcome!"}, "html_url": "/courses/7/announcements/1"}
    inputs_path = fixture_json(adapter, "planner_items.json", {
        "course": raw_course, "quiz": raw_quiz, "event": raw_event,
        "discussion_default": raw_discussion_default, "announcement": raw_announcement,
    })
    codes = {7: "CPSC 121"}
    course = canvas.to_course(raw_course)
    items = [
        canvas.to_item(raw_quiz, codes),
        canvas.to_item(raw_event, {}),
        canvas.to_item(raw_discussion_default, {}),
        canvas.to_item(raw_announcement, {}),
    ]
    golden(adapter, "planner_items_mapping", [inputs_path], "hub.canvas.to_course, hub.canvas.to_item",
           records(courses=[course], items=items),
           extra={"note": "kinds: quiz(deadline/quiz), calendar_event(deadline/event, url already absolute -> "
                          "not double-prefixed), discussion_topic(task/assignment default), "
                          "announcement(task/announcement, due always None)"})

    # -- test_to_undated_item --
    raw_undated = {"name": "Reading response", "html_url": "/courses/7/assignments/9",
                   "has_submitted_submissions": True}
    inputs_path = fixture_json(adapter, "undated_assignment.json", raw_undated)
    item = canvas.to_undated_item(raw_undated, "CPSC 121")
    golden(adapter, "undated_assignment", [inputs_path], "hub.canvas.to_undated_item(a, 'CPSC 121')",
           records(items=[item]))

    # -- test_done_from_submissions / test_done_from_submissions_also_honors_the_manual_complete_checkbox --
    # Folded into to_item calls (done is a field on Item, not its own record type).
    done_cases = [
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "A"},
         "html_url": "/a/1", "submissions": {"submitted": True, "excused": False}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "B"},
         "html_url": "/a/2", "submissions": {"submitted": False, "excused": True}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "C"},
         "html_url": "/a/3", "submissions": {"submitted": False, "excused": False}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "D"},
         "html_url": "/a/4", "submissions": False},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "E"},
         "html_url": "/a/5", "submissions": False, "planner_override": {"marked_complete": True}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "F"},
         "html_url": "/a/6", "planner_override": {"marked_complete": True}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "G"},
         "html_url": "/a/7", "submissions": {"submitted": False}, "planner_override": {"marked_complete": False}},
        {"course_id": 7, "plannable_type": "assignment", "plannable": {"title": "H"},
         "html_url": "/a/8", "planner_override": None},
    ]
    inputs_path = fixture_json(adapter, "done_from_submissions_cases.json", done_cases)
    items = [canvas.to_item(c, codes) for c in done_cases]
    golden(adapter, "done_from_submissions", [inputs_path], "hub.canvas.to_item (done_from_submissions cases)",
           records(items=items),
           extra={"note": "titles A..H exercise: submitted, excused, neither, submissions=False, "
                          "marked_complete alone, marked_complete with no submissions key, "
                          "submitted=False+marked_complete=False, planner_override=None"})

    # -- test_extension_capture_uses_the_same_canvas_model_mapping (hub/captures.py dispatch) --
    capture = {
        "source": "canvas",
        "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
        "planner": [{"course_id": 7, "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z",
                     "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                     "submissions": {"submitted": True}}],
        "undated": [{"course_id": 7, "name": "Reading", "due_at": None,
                     "html_url": "https://canvas.ubc.ca/courses/7/assignments/9",
                     "has_submitted_submissions": False}],
    }
    inputs_path = fixture_json(adapter, "extension_capture.json", capture)
    c_courses, c_items = captures.parse(capture)
    golden(adapter, "extension_capture", [inputs_path], "hub.captures.parse (source=canvas)",
           records(courses=c_courses, items=c_items))

    # -- extension/canvas-capture.test.mjs: node unavailable on this box (checked:
    #    `node --version` -> not found), so the capture JS would produce is
    #    reconstructed by hand-tracing extension/providers/canvas.js (recorded
    #    below as the fixture), then run through the REAL Python parse_capture -
    #    only the *input* is hand-derived, the output is oracle-verified. --
    js_capture_1 = {
        "source": "canvas", "captured_at": "2026-09-27T12:00:00.000Z",
        "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models",
                     "term": {"name": "2026W1"}, "enrollments": [{"computed_current_score": 88}]}],
        "planner": [{"course_id": 7, "context_name": "", "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z", "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                     "submissions": {"submitted": False, "excused": False},
                     "planner_override": {"marked_complete": False}}],
        "undated": [{"course_id": 7, "name": "Reading", "due_at": None,
                     "html_url": "https://canvas.ubc.ca/courses/7/assignments/9",
                     "has_submitted_submissions": True}],
    }
    inputs_path = fixture_json(adapter, "extension_js_capture_minimal.json", js_capture_1)
    c_courses, c_items = canvas.parse_capture(js_capture_1)
    golden(adapter, "extension_js_capture_minimal", [inputs_path], "hub.canvas.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "input hand-derived from extension/providers/canvas.js + "
                          "extension/canvas-capture.test.mjs's 'captures minimum Canvas JSON "
                          "and strips secret URL parameters' test (secret fields/access_token "
                          "already stripped by the JS layer per that test); output is real "
                          "hub.canvas.parse_capture, not hand-computed"})

    js_capture_completed = {
        "source": "canvas", "captured_at": "2026-09-27T00:00:00.000Z",
        "courses": [], "undated": [],
        "planner": [{"course_id": 7, "context_name": "", "plannable_type": "quiz",
                     "plannable_date": "2026-09-30T06:59:00Z", "plannable": {"title": "Quiz 2"},
                     "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                     "submissions": {"submitted": True, "excused": False},
                     "planner_override": {"marked_complete": False}}],
    }
    inputs_path = fixture_json(adapter, "extension_js_capture_completed.json", js_capture_completed)
    c_courses, c_items = canvas.parse_capture(js_capture_completed)
    golden(adapter, "extension_js_capture_completed", [inputs_path], "hub.canvas.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "extension/canvas-capture.test.mjs's 'completed planner submission "
                          "survives the Canvas capture' test: submissions.submitted=True must "
                          "still map to Item.done=True with no course rows at all"})


# ---------------------------------------------------------------------------
# canvas_ics (hub/ics.py's parse()) — the inbound .ics feed parser. Security/
# host-allowlist/SSRF-guard behaviour (fetch_untrusted, is_allowed_feed_host,
# the feed cookie) is boolean/string, not record-shaped; out of scope here.
# ---------------------------------------------------------------------------

CANVAS_FEED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-99
DTSTART:20260930T065900Z
SUMMARY:Quiz 2 [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-55
DTSTART:20261002T170000Z
SUMMARY:Office hours [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-101
DTSTART;VALUE=DATE:20261005
SUMMARY:Reading week starts [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261010T000000Z
SUMMARY:Untagged item
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-202
DTSTART:20261012T065900Z
SUMMARY:Lab [make-up] [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
END:VCALENDAR
"""

NAIVE_FEED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART:20261005T235900
SUMMARY:Naive deadline
END:VEVENT
END:VCALENDAR
"""


def harvest_canvas_ics():
    adapter = "canvas_ics"

    feed_path = fixture_text(adapter, "canvas_feed.ics", CANVAS_FEED)
    items = ics.parse(CANVAS_FEED, source="canvas")
    golden(adapter, "canvas_feed", [feed_path], "hub.ics.parse(text, source='canvas')",
           records(items=items),
           extra={"note": "covers: kind/category from UID not the shared generic calendar URL; "
                          "deep link rebuilt from UID id + course id in the generic URL; two "
                          "items sharing the same generic URL no longer collide; all-day "
                          "DTSTART;VALUE=DATE -> 23:59 America/Vancouver; unrecognized UID falls "
                          "back to url-sniffed kind with no course/url; a title containing its "
                          "own [brackets] still gets the real trailing [COURSE] suffix stripped"})

    moodle_generic_path = fixture_text(adapter, "canvas_feed_as_moodle.ics", CANVAS_FEED)
    items_as_moodle = ics.parse(CANVAS_FEED, source="moodle")
    golden(adapter, "canvas_feed_as_moodle_source", [moodle_generic_path],
           "hub.ics.parse(text, source='moodle')", records(items=items_as_moodle),
           extra={"note": "same feed text tagged source='moodle' - Moodle feeds don't carry a "
                          "[COURSE] suffix, course comes back ''"})

    naive_path = fixture_text(adapter, "naive_datetime.ics", NAIVE_FEED)
    items_naive = ics.parse(NAIVE_FEED, source="moodle")
    golden(adapter, "naive_datetime_gets_vancouver_tz", [naive_path],
           "hub.ics.parse(text, source='moodle')", records(items=items_naive),
           extra={"note": "a feed with no timezone info at all must not produce a naive due"})


# ---------------------------------------------------------------------------
# prairielearn (hub/prairielearn.py) — HTML rows are real markup captured
# from a live UBC course (CPSC 317, 2026W1), per that module's own docstring.
# ---------------------------------------------------------------------------

PL_BASE = "https://us.prairielearn.com"

PL_OPEN_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">PA1</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/14835025/">A Dictionary Client</a></td>
  <td class="text-center align-middle">
    100% until 23:59, Sun, Sep 27
    <button data-bs-content="
    &lt;table&gt;
      &lt;tr&gt;&lt;th&gt;Credit&lt;/th&gt;&lt;th&gt;Start&lt;/th&gt;&lt;th&gt;End&lt;/th&gt;&lt;/tr&gt;
      &lt;tr&gt;&lt;td&gt;100&lt;/td&gt;&lt;td&gt;2026-09-14 09:00:00 (PDT)&lt;/td&gt;&lt;td&gt;2026-09-27 23:59:59 (PDT)&lt;/td&gt;&lt;/tr&gt;
      &lt;tr&gt;&lt;td&gt;70&lt;/td&gt;&lt;td&gt;2026-09-27 23:59:59 (PDT)&lt;/td&gt;&lt;td&gt;2026-10-04 23:59:59 (PDT)&lt;/td&gt;&lt;/tr&gt;
      &lt;tr&gt;&lt;td&gt;0&lt;/td&gt;&lt;td&gt;2026-10-11 23:59:59 (PDT)&lt;/td&gt;&lt;td&gt;—&lt;/td&gt;&lt;/tr&gt;
    &lt;/table&gt;
  "></button>
  </td>
  <td class="text-center align-middle">100%</td>
</tr>
"""
PL_NOT_OPEN_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">PA2</span></td>
  <td class="align-middle"><span class="text-muted">Implementing a DNS Client</span></td>
  <td class="text-center align-middle"><span class="text-muted">Available 09:00, Mon, Sep 28</span></td>
  <td class="text-center align-middle">Not started</td>
</tr>
"""
PL_CLOSED_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">QUIZ</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/1">Network Delay</a></td>
  <td class="text-center align-middle"></td>
  <td class="text-center align-middle">80%</td>
</tr>
"""
PL_CLOSED_NEVER_ATTEMPTED_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">PRAC</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/2">Modern Past Due Practice</a></td>
  <td class="text-center align-middle"></td>
  <td class="text-center align-middle">0%</td>
</tr>
"""


def _pl_row(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").find("tr")


def harvest_prairielearn():
    adapter = "prairielearn"

    open_path = fixture_text(adapter, "open_row.html", PL_OPEN_ROW)
    not_open_path = fixture_text(adapter, "not_open_row.html", PL_NOT_OPEN_ROW)
    closed_path = fixture_text(adapter, "closed_row.html", PL_CLOSED_ROW)
    closed_never_path = fixture_text(adapter, "closed_never_attempted_row.html", PL_CLOSED_NEVER_ATTEMPTED_ROW)
    mst_path = fixture_text(adapter, "open_row_mst.html", PL_OPEN_ROW.replace("(PDT)", "(MST)"))

    items = [
        prairielearn.to_item(_pl_row(PL_OPEN_ROW), "CPSC 317", "Programming Assignments",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_NOT_OPEN_ROW), "CPSC 317", "Programming Assignments",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_CLOSED_ROW), "CPSC 317", "Quizzes",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_CLOSED_NEVER_ATTEMPTED_ROW), "CPSC 317", "Quizzes",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_OPEN_ROW), "CPSC 317", "Practice for Quizzes",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_OPEN_ROW), "CPSC 317", "Formal Quizzes (repeated for practice)",
                             "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_OPEN_ROW.replace("(PDT)", "(MST)")),
                             "CPSC 317", "Programming Assignments", "prairielearn", PL_BASE, "221053"),
        prairielearn.to_item(_pl_row(PL_OPEN_ROW), "MECH 260", "Programming Assignments",
                             "prairielearn_ok", "https://prairielearn.ok.ubc.ca", "221053"),
    ]
    golden(adapter, "assessment_rows", [open_path, not_open_path, closed_path, closed_never_path, mst_path],
           "hub.prairielearn.to_item", records(items=items),
           extra={"note": "rows in order: open/100%-done, not-yet-open/no-due, closed-under-100pct-done, "
                          "closed-never-attempted-0pct-not-done, group->quiz, group->exam, MST offset "
                          "(-07:00, same as PDT), and a second campus (prairielearn_ok) getting its own "
                          "source/base"})

    # to_course: real parse + the ponytail fallback for an unparseable title.
    courses = [
        prairielearn.to_course("221053", "CPSC 317: Internet Computing, 2026 Winter Term 1"),
        prairielearn.to_course("999", "Some unparseable title with no course code"),
    ]
    inputs_path = fixture_json(adapter, "course_titles.json",
                               ["CPSC 317: Internet Computing, 2026 Winter Term 1",
                                "Some unparseable title with no course code"])
    golden(adapter, "course_title_parsing", [inputs_path], "hub.prairielearn.to_course",
           records(courses=courses),
           extra={"note": "second case: title doesn't match COURSE_TITLE -> falls back to the raw "
                          "text as code/title, term left blank, rather than crashing"})

    # parse_capture (tests/test_experimental_captures.py's
    # test_prairielearn_capture_reuses_live_fixture_mapping)
    capture = {"source": "prairielearn", "origin": "https://us.prairielearn.com",
               "courses": [{"ci_id": "221053",
                            "title": "CPSC 317: Internet Computing, 2026 Winter Term 1",
                            "assessments": [{
                                "title": "A Dictionary Client", "group": "Programming Assignments",
                                "href": "/pl/course_instance/221053/assessment_instance/14835025/",
                                "due_text": "2026-09-27 23:59:59 (PDT)",
                                "score_text": "100%", "credit_empty": False,
                            }]}]}
    inputs_path = fixture_json(adapter, "parse_capture.json", capture)
    c_courses, c_items = prairielearn.parse_capture(capture)
    golden(adapter, "parse_capture", [inputs_path], "hub.prairielearn.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"note": "must equal the real to_item() mapping of the equivalent live-scraped "
                          "OPEN_ROW - the same assessment, captured by the extension instead of "
                          "scraped server-side"})


# ---------------------------------------------------------------------------
# webwork (hub/webwork.py) — markup structurally identical to a real UBC
# course's WeBWorK page (webwork.elearning.ubc.ca, per that module's docstring).
# ---------------------------------------------------------------------------

WW_OPEN_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="open"
    data-set-type="default" data-urgency-sort-order="0" data-name-sort-order="4">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/HW1?effectiveUser=abc123">HW1</a></div>
    <div class="font-sm">Open. Due October 1, 2026, 11:59:00 PM PDT.</div>
    <div class="font-sm"></div>
  </div>
  <div class="hardcopy"><a class="hardcopy-link" href="/webwork2/MATH_101/hardcopy?selected_sets=HW1"></a></div>
</li>
"""
WW_NOT_OPEN_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="not-open"
    data-set-type="default" data-urgency-sort-order="2" data-name-sort-order="5">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><span class="set-id-tooltip" data-bs-title="Upcoming material">HW2</span></div>
    <div class="font-sm">Will open on September 30, 2026, 12:01:00 AM PDT.</div>
    <div class="font-sm"></div>
  </div>
</li>
"""
WW_PAST_DUE_WITH_DATE_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="past-due"
    data-set-type="default" data-urgency-sort-order="3" data-name-sort-order="3">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/HW0?effectiveUser=abc123">HW0</a></div>
    <div class="font-sm">Answers available for review on September 28, 2026, 11:59:00 PM PDT.</div>
    <div class="font-sm"></div>
  </div>
  <div class="hardcopy"><a class="hardcopy-link" href="/webwork2/MATH_101/hardcopy?selected_sets=HW0"></a></div>
</li>
"""
WW_PAST_DUE_NO_DATE_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="past-due"
    data-set-type="default" data-urgency-sort-order="4" data-name-sort-order="1">
  <div><i class="set-id-tooltip fa-solid fa-book-open" data-bs-title="Regular Assignment"></i>
    <span class="visually-hidden">Regular Assignment</span></div>
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/Diagnostic?effectiveUser=abc123">Diagnostic</a></div>
    <div class="font-sm">Answers available for review.</div>
    <div class="font-sm"></div>
  </div>
</li>
"""
WW_QUIZ_ROW = """
<li class="list-group-item d-flex align-items-center justify-content-between" data-set-status="open"
    data-set-type="test" data-urgency-sort-order="0" data-name-sort-order="4">
  <div class="ms-3 me-auto">
    <div dir="ltr"><a class="fw-bold set-id-tooltip" href="/webwork2/MATH_101/Quiz1?effectiveUser=abc123">Quiz1</a></div>
    <div class="font-sm">Open. Due October 3, 2026, 11:59:00 PM PDT.</div>
  </div>
</li>
"""


def _ww_li(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser").find("li")


def harvest_webwork():
    adapter = "webwork"
    base = "https://webwork.example.edu/"

    paths = [
        fixture_text(adapter, "open_row.html", WW_OPEN_ROW),
        fixture_text(adapter, "not_open_row.html", WW_NOT_OPEN_ROW),
        fixture_text(adapter, "past_due_with_date_row.html", WW_PAST_DUE_WITH_DATE_ROW),
        fixture_text(adapter, "past_due_no_date_row.html", WW_PAST_DUE_NO_DATE_ROW),
        fixture_text(adapter, "quiz_row.html", WW_QUIZ_ROW),
    ]
    items = [
        webwork.to_item(_ww_li(WW_OPEN_ROW), "MATH 101", base=base),
        webwork.to_item(_ww_li(WW_NOT_OPEN_ROW), "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101"),
        webwork.to_item(_ww_li(WW_PAST_DUE_WITH_DATE_ROW), "MATH 101", base=base),
        webwork.to_item(_ww_li(WW_PAST_DUE_NO_DATE_ROW), "MATH 101"),
        webwork.to_item(_ww_li(WW_QUIZ_ROW), "MATH 101"),
    ]
    golden(adapter, "problem_set_rows", paths, "hub.webwork.to_item", records(items=items),
           extra={"note": "open(due+link, done always None - no score signal on this page), "
                          "not-open(no link, synthetic stable url, no due - open date isn't a due "
                          "date), past-due-with-date(no due - that date is when answers unlock, "
                          "not the deadline), past-due-no-date(degrades cleanly), "
                          "data-set-type=test -> kind quiz/category deadline"})

    a = webwork.to_item(_ww_li(WW_NOT_OPEN_ROW), "MATH 101", base="https://webwork.example.edu/webwork2/MATH_101")
    b = webwork.to_item(_ww_li(WW_NOT_OPEN_ROW.replace(">HW2<", ">HW3<")), "MATH 101",
                        base="https://webwork.example.edu/webwork2/MATH_101")
    inputs_path = fixture_json(adapter, "two_not_open_sets.json", {"a": "HW2", "b": "HW3 (HW2 row w/ name swapped)"})
    golden(adapter, "two_not_open_sets_distinct_urls", [inputs_path], "hub.webwork.to_item",
           records(items=[a, b]),
           extra={"note": "regression: two not-yet-open sets in the same course must not collide "
                          "on the same synthesized url"})


# ---------------------------------------------------------------------------
# workday (hub/workday.py) — real anonymised export fixtures
# (fixtures/workday_view_my_courses.xlsx, fixtures/workday_truncated_dimension.xlsx
# on main; see main's docs/workday-testing.md) copied verbatim, plus small
# synthetic single-row workbooks built the same way tests/test_workday_schedule.py
# builds them (openpyxl, no randomness -> byte-identical across runs).
# ---------------------------------------------------------------------------


_FIXED_WORKBOOK_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pin_workbook_timestamps(wb):
    # openpyxl re-stamps properties.modified to datetime.now() *during*
    # save() itself (confirmed: setting it beforehand doesn't survive the
    # save call), so this alone isn't enough - see _pin_xlsx_modified() below,
    # called after save(), for what actually makes the written file
    # reproducible.
    wb.properties.created = _FIXED_WORKBOOK_TIMESTAMP
    wb.properties.modified = _FIXED_WORKBOOK_TIMESTAMP


_CORE_XML_MODIFIED_RE = re.compile(
    rb'(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)')


def _pin_xlsx_modified(path):
    """Rewrite docProps/core.xml's <dcterms:modified> to a fixed timestamp
    after save() (openpyxl overwrites it with datetime.now() during save()
    itself, regardless of what properties.modified held beforehand) - the
    one remaining source of non-reproducibility across harvester runs for
    every generated .xlsx fixture."""
    import zipfile
    path = Path(path)
    with zipfile.ZipFile(path, "r") as zin:
        entries = [(item, zin.read(item.filename)) for item in zin.infolist()]
    out_bytes_by_name = {}
    for item, content in entries:
        if item.filename == "docProps/core.xml":
            content = _CORE_XML_MODIFIED_RE.sub(
                rb"\g<1>" + _FIXED_WORKBOOK_TIMESTAMP.strftime("%Y-%m-%dT%H:%M:%SZ").encode() + rb"\g<2>",
                content,
            )
        out_bytes_by_name[item.filename] = (item, content)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item, content in out_bytes_by_name.values():
            item.date_time = (1980, 1, 1, 0, 0, 0)
            zout.writestr(item, content)


def _one_row_workday_workbook(path, meeting_pattern, instructional_format="Lecture",
                              course_listing="BMEG 000 - Fake Thermodynamics"):
    import openpyxl
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Instructional Format", "Meeting Patterns"])
    sheet.append([course_listing, instructional_format, meeting_pattern])
    _pin_workbook_timestamps(wb)
    wb.save(path)
    _pin_xlsx_modified(path)


def _no_meeting_patterns_workbook(path):
    import openpyxl
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "View My Courses"
    sheet.append(["Course Listing", "Section"])
    sheet.append(["BMEG 000 - Fake Thermodynamics", "101"])
    _pin_workbook_timestamps(wb)
    wb.save(path)
    _pin_xlsx_modified(path)


def harvest_workday():
    adapter = "workday"

    view_my_courses = fixture_copy(adapter, "view_my_courses.xlsx",
                                   f"{ORACLE_ROOT}/fixtures/workday_view_my_courses.xlsx")
    truncated_dimension = fixture_copy(adapter, "truncated_dimension.xlsx",
                                       f"{ORACLE_ROOT}/fixtures/workday_truncated_dimension.xlsx")

    courses = workday.parse_workday_courses(str(fixture_path(adapter, "view_my_courses.xlsx")), term="2026W1")
    golden(adapter, "courses_view_my_courses", [view_my_courses],
           "hub.workday.parse_workday_courses(path, term='2026W1')", records(courses=courses),
           extra={"note": "3 unique courses deduped from repeated meeting-component rows; "
                          "BMEG 002 has no ' - ' separator -> raw listing text as title"})

    meetings = workday.parse_workday_schedule(str(fixture_path(adapter, "view_my_courses.xlsx")), term="2026W1")
    golden(adapter, "schedule_view_my_courses", [view_my_courses],
           "hub.workday.parse_workday_schedule(path, term='2026W1')", records(meetings=meetings),
           extra={"note": "one Meeting per component row (BMEG 000 keeps both its Lecture and Lab, "
                          "unlike parse_workday_courses which dedupes to one Course)"})

    courses_t = workday.parse_workday_courses(str(fixture_path(adapter, "truncated_dimension.xlsx")), term="2026W1")
    golden(adapter, "courses_truncated_dimension", [truncated_dimension],
           "hub.workday.parse_workday_courses(path, term='2026W1')", records(courses=courses_t),
           extra={"note": "regression for e3db118: the file's declared <dimension ref> understates "
                          "the real range (A1:A1, but 8 rows exist) - read_only openpyxl trusting it "
                          "silently drops rows"})

    # Stray cell at Excel's max address (#49 item 13): built from the same
    # base fixture the way tests/test_workday_stray_cell.py does.
    import openpyxl
    wb = openpyxl.load_workbook(f"{ORACLE_ROOT}/fixtures/workday_view_my_courses.xlsx")
    wb.active["XFD1048576"] = "stray"
    _pin_workbook_timestamps(wb)
    stray_path = FIXTURES / adapter / "stray_cell.xlsx"
    stray_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(stray_path)
    _pin_xlsx_modified(stray_path)
    WRITTEN.append(("fixture", stray_path))
    courses_stray = workday.parse_workday_courses(str(stray_path), term="2026W1")
    golden(adapter, "courses_stray_cell_at_max_address", [f"{adapter}/stray_cell.xlsx"],
           "hub.workday.parse_workday_courses(path, term='2026W1')", records(courses=courses_stray),
           extra={"note": "must still parse the same 3 courses without hanging on the full "
                          "1M x 16K grid (#49 item 13 / web/lib/workday.js#57's Python twin)"})

    # Instructional-format -> Meeting.kind mapping, one small workbook per format.
    format_cases = [("Lecture", "lecture"), ("Laboratory", "lab"), ("Seminar", "seminar"),
                    ("Tutorial", "tutorial"), ("Discussion", "tutorial"), ("Exam", "exam"),
                    ("Something Unseen", "class")]
    kind_meetings = []
    kind_inputs = []
    for fmt, _expected in format_cases:
        name = f"kind_{re.sub(r'[^a-z]+', '_', fmt.lower()).strip('_')}.xlsx"
        p = FIXTURES / adapter / name
        _one_row_workday_workbook(p, "2026-09-08 - 2026-12-05 | Mon Wed Fri | 10:00 a.m. - 11:00 a.m. | Room 1",
                                  instructional_format=fmt)
        WRITTEN.append(("fixture", p))
        kind_inputs.append(f"{adapter}/{name}")
        kind_meetings += workday.parse_workday_schedule(str(p), term="2026W1")
    golden(adapter, "schedule_instructional_format_kind_mapping", kind_inputs,
           "hub.workday.parse_workday_schedule(path, term='2026W1')", records(meetings=kind_meetings),
           extra={"note": "one single-row workbook per Instructional Format value, concatenated in "
                          "the order: Lecture, Laboratory, Seminar, Tutorial, Discussion, Exam, "
                          "Something Unseen (unlisted -> kind 'class')"})

    edge_cases = {
        "no_recognizable_days": "2026-09-08 - 2026-12-05 | TBD | 10:00 a.m. - 11:00 a.m. | Room 1",
        "unparseable_time": "2026-09-08 - 2026-12-05 | Mon Wed Fri | TBD | Room 1",
        "bare_dash": "-",
    }
    for case_name, pattern in edge_cases.items():
        p = FIXTURES / adapter / f"edge_{case_name}.xlsx"
        _one_row_workday_workbook(p, pattern)
        WRITTEN.append(("fixture", p))
        meetings_edge = workday.parse_workday_schedule(str(p), term="2026W1")
        golden(adapter, f"schedule_edge_{case_name}", [f"{adapter}/edge_{case_name}.xlsx"],
               "hub.workday.parse_workday_schedule(path, term='2026W1')", records(meetings=meetings_edge),
               extra={"note": "must degrade to no Meetings for this line, never guess"})

    multi_pattern = ("2026-09-08 - 2026-12-05 | Mon Wed | 10:00 a.m. - 11:00 a.m. | Room 1\n"
                     "2026-09-08 - 2026-12-05 | Fri | 09:00 a.m. - 10:00 a.m. | Room 2")
    p = FIXTURES / adapter / "multi_line_pattern.xlsx"
    _one_row_workday_workbook(p, multi_pattern)
    WRITTEN.append(("fixture", p))
    meetings_multi = workday.parse_workday_schedule(str(p), term="2026W1")
    golden(adapter, "schedule_multiple_lines_one_cell", [f"{adapter}/multi_line_pattern.xlsx"],
           "hub.workday.parse_workday_schedule(path, term='2026W1')", records(meetings=meetings_multi),
           extra={"note": "a lecture with two distinct weekly slots in one cell (newline-separated) "
                          "must produce two Meetings, not one or a crash"})

    p = FIXTURES / adapter / "no_meeting_patterns_column.xlsx"
    _no_meeting_patterns_workbook(p)
    WRITTEN.append(("fixture", p))
    meetings_none = workday.parse_workday_schedule(str(p), term="2026W1")
    golden(adapter, "schedule_no_meeting_patterns_column", [f"{adapter}/no_meeting_patterns_column.xlsx"],
           "hub.workday.parse_workday_schedule(path, term='2026W1')", records(meetings=meetings_none),
           extra={"note": "an older export missing the Meeting Patterns column degrades to [], "
                          "never crashes"})


# ---------------------------------------------------------------------------
# bookstore (hub/bookstore.py) — real, anonymised UBC Bookstore pages copied
# verbatim from main's fixtures/bookstore/ (no student data was ever in them:
# public course/textbook listings; see tests/test_bookstore.py's own docstring).
# ---------------------------------------------------------------------------

BOOKSTORE_SYNTHETIC_ITEM = """
<div class="course_search_body">
<div class="course_item">
<div class="course_item_header">
<div class="course_item_status"> Not Required
:</div>
<div class="course_item_title">Some Optional Companion Book</div>
</div>
<div class="course_item_data">
<div class="course_item_item"><span>Item#:</span> 1111111111</div>
</div>
<div class="course_item_options"><div class="course_item_buy"><div class="options">
<h3 class="accordion_h3">Buy New $50</h3>
<h3>Buy Used Rental $35.00</h3>
</div></div></div>
</div>
</div>
"""

BOOKSTORE_MALFORMED_SECTION = (
    '<div id="course_form"><ul><li class="course" id="weird-id">'
    '<label for="x">Not the usual format</label></li></ul></div>'
)


def harvest_bookstore():
    adapter = "bookstore"

    terms_path = fixture_copy(adapter, "terms.html", f"{ORACLE_ROOT}/fixtures/bookstore/terms.html")
    sections_path = fixture_copy(adapter, "sections_cpsc.html", f"{ORACLE_ROOT}/fixtures/bookstore/sections_cpsc.html")
    textbooks_path = fixture_copy(adapter, "textbooks_cpsc121.html", f"{ORACLE_ROOT}/fixtures/bookstore/textbooks_cpsc121.html")
    textbooks_none_path = fixture_copy(adapter, "textbooks_none.html", f"{ORACLE_ROOT}/fixtures/bookstore/textbooks_none.html")
    page1_path = fixture_copy(adapter, "products_page1.json", f"{ORACLE_ROOT}/fixtures/bookstore/products_page1.json")
    page2_path = fixture_copy(adapter, "products_page2.json", f"{ORACLE_ROOT}/fixtures/bookstore/products_page2.json")

    sections = bookstore._parse_sections((FIXTURES / adapter / "sections_cpsc.html").read_text())
    courses = [bookstore._course_from_section(s, "2026W1") for s in sections]
    golden(adapter, "sections_to_courses", [sections_path], "hub.bookstore._parse_sections, "
           "hub.bookstore._course_from_section", records(courses=courses),
           extra={"note": f"{len(courses)} real CPSC sections, codes canonicalised "
                          "(e.g. bookstore's 'CPSC121' -> 'CPSC 121')"})

    malformed_path = fixture_text(adapter, "malformed_section.html", BOOKSTORE_MALFORMED_SECTION)
    weird_sections = bookstore._parse_sections(BOOKSTORE_MALFORMED_SECTION)
    weird_courses = [bookstore._course_from_section(s, "2026W1") for s in weird_sections]
    golden(adapter, "malformed_section_id_fallback", [malformed_path],
           "hub.bookstore._parse_sections, hub.bookstore._course_from_section", records(courses=weird_courses),
           extra={"note": "a section id with fewer than the usual 5 comma parts degrades instead "
                          "of raising IndexError"})

    books = bookstore._parse_textbooks((FIXTURES / adapter / "textbooks_cpsc121.html").read_text(), "CPSC 121")
    golden(adapter, "textbooks_cpsc121", [textbooks_path], "hub.bookstore._parse_textbooks",
           records(textbooks=books),
           extra={"note": "real listing: required book, new price ($302.88) preferred over the "
                          "cheaper digital tier"})

    books_none = bookstore._parse_textbooks((FIXTURES / adapter / "textbooks_none.html").read_text(), "CPSC 100")
    golden(adapter, "textbooks_none_listed", [textbooks_none_path], "hub.bookstore._parse_textbooks",
           records(textbooks=books_none),
           extra={"note": "'No course materials are currently listed' -> [], not a failure"})

    synthetic_path = fixture_text(adapter, "synthetic_price_and_status.html", BOOKSTORE_SYNTHETIC_ITEM)
    synthetic_books = bookstore._parse_textbooks(BOOKSTORE_SYNTHETIC_ITEM, "K1")
    golden(adapter, "textbooks_price_without_cents_and_not_required", [synthetic_path],
           "hub.bookstore._parse_textbooks", records(textbooks=synthetic_books),
           extra={"note": "'$50' (no cents) must not be silently dropped by the price regex; "
                          "'Not Required' must not be flagged required by a naive substring check "
                          "on 'required'"})

    # attach_store_links: real code path, network substituted with the same
    # fixture pages tests/test_bookstore.py's own monkeypatch uses.
    page1_text = (FIXTURES / adapter / "products_page1.json").read_text()
    page2_text = (FIXTURES / adapter / "products_page2.json").read_text()
    pages = [page1_text, page2_text]

    def _fake_get(url, **params):
        return pages[params["page"] - 1] if params.get("page", 1) <= len(pages) else json.dumps({"products": []})

    real_get = bookstore._get
    bookstore._get = _fake_get
    try:
        linked = bookstore.attach_store_links([
            Textbook(course="CPSC 121", title="Discrete Math", isbn="9781337694193",
                    required=True, price=302.88, url=""),
            Textbook(course="CPSC 121", title="Companion", isbn="0000000000000",
                    required=False, price=None, url=""),
        ])
    finally:
        bookstore._get = real_get
    inputs_path = fixture_json(adapter, "attach_store_links_input.json", {
        "textbooks": [{"isbn": "9781337694193"}, {"isbn": "0000000000000"}],
        "catalog_pages": [page1_path, page2_path],
    })
    golden(adapter, "attach_store_links", [inputs_path, page1_path, page2_path],
           "hub.bookstore.attach_store_links (network substituted with the paginated Shopify "
           "products.json fixtures above)", records(textbooks=linked),
           extra={"note": "a matching ISBN gets its real store link; an unmatched one keeps url='' "
                          "rather than crashing"})


# ---------------------------------------------------------------------------
# key_dates (hub/key_dates.py) — public UBC key dates, no login, same for
# every student; hand-maintained data (no HTML/JSON fixture exists on main).
# ---------------------------------------------------------------------------

NOW_A = "2026-09-28T09:00:00-07:00"   # PDT, the run's fixed "now"
NOW_B = "2026-11-15T09:00:00-08:00"   # PST, after Nov 1 (BC's autumn clock change)


def harvest_key_dates():
    adapter = "key_dates"
    now_a = datetime.fromisoformat(NOW_A)
    now_b = datetime.fromisoformat(NOW_B)

    for campus in sorted(key_dates.KEY_DATES):
        for label, now in (("now_a", now_a), ("now_b", now_b)):
            courses, items = key_dates.fetch(campus, now=now)
            golden(adapter, f"{campus.lower()}_{label}", [], "hub.key_dates.fetch(campus, term, now=now)",
                   records(courses=courses, items=items), now=now.isoformat(), extra={"campus": campus})

    courses, items = key_dates.fetch("MARS_U", now=now_a)
    golden(adapter, "unknown_campus", [], "hub.key_dates.fetch('MARS_U', now=now)",
           records(courses=courses, items=items), now=now_a.isoformat(),
           extra={"note": "an unlisted campus still gets a Course row (the campus code itself), "
                          "just no dated items"})


# ---------------------------------------------------------------------------
# brightspace (hub/brightspace.py) — anonymised copy of a real
# /d2l/api/lp/1.50/enrollments/myenrollments/ response (Terrace, 2026-09-26,
# ubc.brightspace.com), per that module's own test docstring. Items are
# always [] (documented gap: no plain JSON due-date endpoint found - see
# hub/brightspace.py's module docstring), so nothing to harvest there.
# ---------------------------------------------------------------------------


def harvest_brightspace():
    adapter = "brightspace"
    enrollment = {
        "OrgUnit": {
            "Id": 12345, "Type": {"Id": 3, "Code": "Course Offering", "Name": "Course Offering"},
            "Name": "MATH_V 100A ALL SECTIONS 2026W1 Differential Calculus with Applications",
            "Code": "MATH_V 100A ALL SECTIONS 2026W1",
            "HomeUrl": "https://example.brightspace.com/d2l/home/12345",
            "ImageUrl": "https://example.brightspace.com/d2l/api/lp/1.9/courses/12345/image",
        },
        "Access": {"IsActive": True, "StartDate": "2026-09-08T07:00:00.000Z",
                   "EndDate": "2027-02-02T06:59:00.000Z", "CanAccess": True,
                   "ClasslistRoleName": "Learner", "LastAccessed": "2026-09-27T04:20:13.077Z"},
        "PinDate": None,
    }
    second_course = {"OrgUnit": {"Id": 222, "Name": "A Second Course", "Code": "SECOND 200"},
                     "Access": {"IsActive": True}, "PinDate": None}
    inputs_path = fixture_json(adapter, "myenrollments_items.json",
                               {"page1": [enrollment], "page2": [second_course]})
    courses = [brightspace.to_course(enrollment), brightspace.to_course(second_course)]
    golden(adapter, "to_course_mapping", [inputs_path], "hub.brightspace.to_course",
           records(courses=courses),
           extra={"note": "real response has no separate section/term field - left blank, not "
                          "guessed; a minimal second-page item (paginated via D2L's Bookmark/"
                          "HasMoreItems cursor) still maps cleanly"})


# ---------------------------------------------------------------------------
# moodle / blackboard / piazza — no dedicated tests/test_<adapter>.py exists
# on main (checked: only referenced via tests/test_experimental_captures.py's
# parse_capture-through-hub.captures cases). Every module itself is marked
# [UNVERIFIED END-TO-END] / [unverified field shape] in its own docstring:
# no live account was ever checked. Inputs below are exactly the payloads
# tests/test_experimental_captures.py uses, so goldens match what main's own
# suite actually asserts (nothing further is invented).
# ---------------------------------------------------------------------------


def harvest_moodle():
    adapter = "moodle"
    capture = {
        "source": "moodle", "origin": "https://moodle.example.edu",
        "courses": [{"shortname": "CPSC101", "fullname": "Intro"}],
        "events": [{"id": 9, "name": "Quiz", "modulename": "quiz",
                    "timesort": 1798000000, "url": "", "course": {"shortname": "CPSC101"}}],
    }
    inputs_path = fixture_json(adapter, "parse_capture.json", capture)
    c_courses, c_items = moodle.parse_capture(capture)
    golden(adapter, "parse_capture", [inputs_path], "hub.moodle.parse_capture", records(courses=c_courses, items=c_items),
           extra={"unverified": True,
                  "note": "no live Moodle account exists on this project (module docstring); "
                          "input is tests/test_experimental_captures.py's own capture. An empty "
                          "event url falls back to the real "
                          "calendar/event.php?id=<id> route, joined against origin"})

    event_assign = {"id": 10, "name": "HW1", "modulename": "assign", "timesort": 1798100000,
                    "url": "https://moodle.example.edu/mod/assign/view.php?id=10",
                    "course": {"shortname": "CPSC101"}}
    inputs_path = fixture_json(adapter, "to_item_assign_default_kind.json", event_assign)
    item = moodle.to_item(event_assign)
    golden(adapter, "to_item_assign_default_kind", [inputs_path], "hub.moodle.to_item",
           records(items=[item]),
           extra={"unverified": True,
                  "note": "modulename 'assign' -> kind 'assignment' (KINDS default), a real url "
                          "already present is used as-is"})


def harvest_blackboard():
    adapter = "blackboard"
    capture = {"source": "blackboard", "courses": [
        {"id": "_1_1", "courseId": "BIOL101", "name": "Biology", "term": {"name": "Fall 2026"}}]}
    inputs_path = fixture_json(adapter, "parse_capture.json", capture)
    c_courses, c_items = blackboard.parse_capture(capture)
    golden(adapter, "parse_capture", [inputs_path], "hub.blackboard.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"unverified": True,
                  "note": "no live Blackboard tenant exists anywhere on this project (module "
                          "docstring: 'EVERYTHING IN THIS MODULE IS AN INFORMED HYPOTHESIS'); "
                          "items is always [] - no confirmed JSON due-date endpoint"})

    course_no_term = {"id": "_2_1", "courseId": "MATH200", "name": "Calculus"}
    inputs_path = fixture_json(adapter, "to_course_no_term.json", course_no_term)
    course = blackboard.to_course(course_no_term)
    golden(adapter, "to_course_missing_term_field", [inputs_path], "hub.blackboard.to_course",
           records(courses=[course]),
           extra={"unverified": True, "note": "?expand=term not honoured/absent -> term left blank"})


def harvest_piazza():
    adapter = "piazza"
    network_pinned = {
        "id": "abc123", "course_number": "CPSC 121", "name": "Models", "term": "Fall 2026",
        "posts": [{"id": "post123", "tags": ["pin"], "bucket_name": "Pinned",
                   "history": [{"subject": "Quiz room"}]}],
    }
    capture = {"source": "piazza", "networks": [network_pinned]}
    inputs_path = fixture_json(adapter, "parse_capture_pinned.json", capture)
    c_courses, c_items = piazza.parse_capture(capture)
    golden(adapter, "parse_capture_pinned_post", [inputs_path], "hub.piazza.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"unverified": True,
                  "note": "cited from the real piazza-api client source (module docstring), never "
                          "run against a live Piazza network. due is always None (no real due-date "
                          "field exists anywhere in scope); a pinned/instructor post's ORIGINAL "
                          "subject (history[0].subject) becomes the title"})

    network_no_number = {"id": "def456", "name": "Some Class", "term": "",
                         "posts": [{"id": "postX", "tags": [], "bucket_name": "Today",
                                    "history": [{"subject": "Just a question"}]}]}
    inputs_path = fixture_json(adapter, "parse_capture_dropped_and_fallback_code.json",
                               {"source": "piazza", "networks": [network_no_number]})
    c_courses2, c_items2 = piazza.parse_capture({"source": "piazza", "networks": [network_no_number]})
    golden(adapter, "parse_capture_non_pinned_dropped_course_number_fallback", [inputs_path],
           "hub.piazza.parse_capture", records(courses=c_courses2, items=c_items2),
           extra={"unverified": True,
                  "note": "course_number absent -> code falls back to name; an ordinary "
                          "(non-pinned, non-instructor) post produces no Item at all"})


# ---------------------------------------------------------------------------
# captures (hub/captures.py) — the dispatcher + normalize(); adapter-specific
# rules are already exercised above, this only covers the dispatch/JSON-
# normalisation layer itself (tests/test_captures.py).
# ---------------------------------------------------------------------------


def harvest_captures():
    adapter = "captures"

    planner = {"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
              "plannable": {"title": "Quiz 2"}, "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3"}
    capture = {"source": "canvas", "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
              "planner": [planner, dict(planner)], "undated": []}
    inputs_path = fixture_json(adapter, "normalize_dedupe_input.json", capture)
    normalized = captures.normalize(capture)
    result_golden(adapter, "normalize_dedupes_by_source_and_url", [inputs_path], "hub.captures.normalize",
           normalized,
           extra={"note": "two identical planner rows (same (source, url) identity) must dedupe to "
                          "one item in the normalized output; due comes back as an ISO string"})

    canvas_capture = {"source": "canvas", "courses": [{"id": 7, "course_code": "CPSC 121", "name": "Models"}],
                      "planner": [{"course_id": 7, "plannable_type": "quiz", "plannable_date": "2026-09-30T06:59:00Z",
                                   "plannable": {"title": "Quiz 2"}, "html_url": "https://canvas.ubc.ca/courses/7/quizzes/3",
                                   "submissions": {"submitted": True, "excused": False},
                                   "planner_override": {"marked_complete": False}}], "undated": []}
    pl_capture = {"source": "prairielearn", "origin": "https://us.prairielearn.com",
                 "courses": [{"ci_id": "221053", "title": "CPSC 317: Internet Computing, 2026 Winter Term 1",
                              "assessments": [{"title": "Quiz 2", "group": "Quizzes",
                                               "href": "/pl/course_instance/221053/assessment_instance/14835025/",
                                               "due_text": "", "score_text": "100%", "credit_empty": False}]}]}
    inputs_path_c = fixture_json(adapter, "normalize_done_canvas_input.json", canvas_capture)
    inputs_path_p = fixture_json(adapter, "normalize_done_prairielearn_input.json", pl_capture)
    result_golden(adapter, "normalize_done_canvas", [inputs_path_c], "hub.captures.normalize",
           captures.normalize(canvas_capture),
           extra={"note": "submissions.submitted=True -> normalized item.done=True"})
    result_golden(adapter, "normalize_done_prairielearn", [inputs_path_p], "hub.captures.normalize",
           captures.normalize(pl_capture),
           extra={"note": "a 100% score with no due_text -> normalized item.done=True"})


# ---------------------------------------------------------------------------
# extension providers (extension/providers/*.js) — `node --version` found
# nothing on this box, so extension/*.test.mjs could not be run directly.
# Each capture below was hand-derived by tracing the provider .js source
# against its own *.test.mjs test (recorded in "extra.note"); it is then fed
# through the REAL Python hub.<source>.parse_capture (or hub.captures.parse),
# so only the *input* is hand-derived - every output is oracle-verified.
# ---------------------------------------------------------------------------


def harvest_extension():
    adapter = "extension"

    # Raw anchors, in DOM order, as capturePrairieLearnIndex() itself reads
    # them (`root.querySelectorAll('a[href^="/pl/course_instance/"]')` ->
    # each `<a>`'s own `href`/`textContent`) - not the already-deduped
    # result. The scenario the note below describes needs all three: the
    # student link, its `/instructor` twin for the same ci_id (deduped,
    # first title wins), and a same-course `/assessments` link, which
    # `_CI_LINK`'s full match (`^/pl/course_instance/(\d+)(?:/instructor)?/?$`)
    # correctly refuses to treat as a course link at all.
    prairielearn_index_anchors = [
        {"href": "/pl/course_instance/221053/", "text": "CPSC 317: Internet Computing, 2026 Winter Term 1"},
        {"href": "/pl/course_instance/221053/instructor", "text": "CPSC 317 (instructor view)"},
        {"href": "/pl/course_instance/221053/assessments", "text": "Assessments"},
    ]
    prairielearn_index_links = [
        {"ci_id": "221053", "title": "CPSC 317: Internet Computing, 2026 Winter Term 1"},
    ]
    inputs_path = fixture_json(adapter, "prairielearn_index_capture.json", prairielearn_index_anchors)
    result_golden(adapter, "prairielearn_index_capture_literal", [inputs_path],
           "extension/providers/prairielearn-index.js capturePrairieLearnIndex() (literal, node unavailable)",
           {"courses": prairielearn_index_links},
           extra={"node_available": False,
                  "note": "extension/prairielearn-capture.test.mjs 'PrairieLearn index discovers "
                          "distinct course instances...': the instructor-link duplicate of the same "
                          "ci_id (221053) is deduped (first title wins), and a link matching a "
                          "DIFFERENT route (/assessments) is not treated as a course link at all"})

    pl_assessment_capture = {"ci_id": "221053", "assessments": [
        {"title": "Quiz 2", "group": "Quizzes",
         "href": "/pl/course_instance/221053/assessment_instance/14835025/",
         "due_text": "2026-09-27 23:59:59 (PDT)", "score_text": "80%", "credit_empty": False},
    ]}
    inputs_path = fixture_json(adapter, "prairielearn_assessments_capture.json", pl_assessment_capture)
    pl_full_capture = {"source": "prairielearn", "origin": "https://us.prairielearn.com",
                       "courses": [{"ci_id": "221053",
                                   "title": "CPSC 317: Internet Computing, 2026 Winter Term 1",
                                   "assessments": pl_assessment_capture["assessments"]}]}
    c_courses, c_items = prairielearn.parse_capture(pl_full_capture)
    golden(adapter, "prairielearn_assessments_capture_through_parse_capture", [inputs_path],
           "extension/providers/prairielearn-assessments.js capturePrairieLearnAssessments() "
           "(literal, node unavailable), piped through the real hub.prairielearn.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "extension/prairielearn-capture.test.mjs 'PrairieLearn assessment rows "
                          "return selected fields, not the popover HTML': only title/group/href/"
                          "due_text/score_text/credit_empty leave the tab, never the raw popover "
                          "markup"})

    moodle_capture = {
        "source": "moodle", "origin": "https://moodle.example.edu",
        "courses": [{"shortname": "CPSC101", "fullname": "Intro"}],
        "events": [{"id": 9, "name": "Quiz", "modulename": "quiz", "timesort": 1798000000,
                    "url": "https://moodle.example.edu/mod/quiz/view.php?id=9", "course": {"shortname": "CPSC101"}}],
    }
    inputs_path = fixture_json(adapter, "moodle_capture.json", moodle_capture)
    c_courses, c_items = moodle.parse_capture(moodle_capture)
    golden(adapter, "moodle_capture_through_parse_capture", [inputs_path],
           "extension/providers/moodle.js captureMoodle() (literal, node unavailable), piped "
           "through the real hub.moodle.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "extension/experimental-capture.test.mjs 'Moodle capture keeps only "
                          "mapper fields and never includes its session key': the token/secret "
                          "query params the JS layer already stripped from the event url are gone "
                          "before this ever reaches Python"})

    blackboard_capture = {"source": "blackboard", "origin": "https://bb.example.edu",
                          "courses": [{"id": "_1_1", "courseId": "BIOL101", "name": "Biology",
                                       "term": {"name": "Fall"}}]}
    inputs_path = fixture_json(adapter, "blackboard_capture.json", blackboard_capture)
    c_courses, c_items = blackboard.parse_capture(blackboard_capture)
    golden(adapter, "blackboard_capture_through_parse_capture", [inputs_path],
           "extension/providers/blackboard.js captureBlackboard() (literal, node unavailable), "
           "piped through the real hub.blackboard.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "extension/experimental-capture.test.mjs 'Blackboard capture returns "
                          "courses only and blocks foreign pagination': the JS layer already "
                          "refuses to follow a nextPage that left its own API origin, so only "
                          "well-formed same-origin course rows ever reach Python"})

    piazza_capture = {"source": "piazza", "networks": [
        {"id": "abc123", "name": "Models", "course_number": "", "term": "",
         "posts": [{"id": "post1", "tags": ["pin"], "bucket_name": "", "history": [{"subject": "Room"}]}]},
    ]}
    inputs_path = fixture_json(adapter, "piazza_capture.json", piazza_capture)
    c_courses, c_items = piazza.parse_capture(piazza_capture)
    golden(adapter, "piazza_capture_through_parse_capture", [inputs_path],
           "extension/providers/piazza.js capturePiazza() (literal, node unavailable), piped "
           "through the real hub.piazza.parse_capture",
           records(courses=c_courses, items=c_items),
           extra={"node_available": False,
                  "note": "extension/experimental-capture.test.mjs 'Piazza capture keeps pinned "
                          "posts but drops ordinary posts': the JS layer's own feed->content.get "
                          "loop already dropped the second, unpinned post before this capture was "
                          "ever built - Python never sees it at all"})


# ---------------------------------------------------------------------------
# export_ics (hub/export_ics.py) — the outbound merged .ics feed, and its
# round trip back through hub.ics.parse() (main's own test ask, #18).
# ---------------------------------------------------------------------------


def harvest_export_ics():
    adapter = "export_ics"
    item_a = Item(course="CPSC 121", category="task", kind="assignment", title="Problem Set 3",
                  due=datetime(2026, 9, 30, 6, 59, tzinfo=timezone.utc),
                  url="https://canvas.ubc.ca/courses/7/assignments/99", source="canvas")
    item_b = Item(course="MATH 100", category="deadline", kind="exam", title="Midterm 1",
                  due=datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc),
                  url="https://canvas.ubc.ca/courses/8/assignments/12", source="canvas")
    item_no_due = Item(course="CPSC 121", category="task", kind="assignment", title="Reading response",
                       due=None, url="https://canvas.ubc.ca/courses/7/assignments/50", source="canvas")
    inputs_path = fixture_json(adapter, "items.json",
                               {"item_a": jsonable(item_a), "item_b": jsonable(item_b),
                                "item_no_due": jsonable(item_no_due)})

    ics_all = export_ics.to_ics([item_a, item_b, item_no_due])
    round_trip = ics.parse(ics_all.decode(), source="canvas")
    result_golden(adapter, "to_ics_all_items", [inputs_path], "hub.export_ics.to_ics([item_a, item_b, item_no_due])",
           {"ics": ics_all.decode(), "round_trip_items": records(items=round_trip)["items"],
            "uid_a": export_ics._uid(item_a), "uid_b": export_ics._uid(item_b),
            "known_kinds": export_ics.known_kinds([item_a, item_b, item_no_due]),
            "color_exam": export_ics.color_for_kind("exam"),
            "color_quiz": export_ics.color_for_kind("quiz"),
            "color_unknown_kind": export_ics.color_for_kind("some-future-provider-kind"),
            "color_fallback": export_ics.KIND_COLOR_FALLBACK},
           extra={"note": "item_no_due is skipped, not crashed on (no DTSTART possible); UID is "
                          "stable per (source, url) and distinct across items; known_kinds lists "
                          "only kinds among items that HAVE a due date, sorted"})

    ics_exam_only = export_ics.to_ics([item_a, item_b], kind="exam")
    result_golden(adapter, "to_ics_filtered_by_kind", [inputs_path], "hub.export_ics.to_ics([item_a, item_b], kind='exam')",
           {"ics": ics_exam_only.decode()},
           extra={"note": "calname becomes 'Lauds: Exam'; only Midterm 1 (kind=exam) is included"})

    ics_no_match = export_ics.to_ics([item_a], kind="exam")
    result_golden(adapter, "to_ics_filtered_no_matches", [inputs_path], "hub.export_ics.to_ics([item_a], kind='exam')",
           {"ics": ics_no_match.decode()},
           extra={"note": "a valid, empty calendar (no VEVENT) when the kind filter matches nothing"})

    ics_empty = export_ics.to_ics([])
    result_golden(adapter, "to_ics_empty_input", [], "hub.export_ics.to_ics([])", {"ics": ics_empty.decode()},
           extra={"note": "a valid calendar with zero events for empty input"})


# ---------------------------------------------------------------------------
# queries (hub/db.py's upcoming/undated/by_course/courses/textbooks/schedule,
# hub.models.status_of) — each scenario below is its own fresh in-memory
# main hub.db, seeded exactly like the corresponding oracle test
# (tests/test_db.py, tests/test_db_schedule.py, tests/test_db_oracle_pr33.py,
# tests/test_key_dates_oracle.py), then dumped at the two fixed "now" values.
# ---------------------------------------------------------------------------

Q_COURSE = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation", grade=88.5)
Q_OTHER_COURSE = Course(code="ENGL 112", section="", term="2026W1", title="Strategies for University Writing")
Q_QUIZ = Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
              due=datetime(2026, 9, 30, 6, 59, tzinfo=timezone.utc), url="https://x/q/1", source="canvas")
Q_BOOK = Textbook(course="CPSC 121", title="Discrete Math", isbn="123", required=True, price=80.0, url="https://x/b/1")
Q_LECTURE = Meeting(course="CPSC 121", kind="lecture", days=["MO", "WE", "FR"],
                    start_time=time_cls(10, 0), end_time=time_cls(11, 0), location="ICCS 101",
                    term_start=date(2026, 9, 8), term_end=date(2026, 12, 5), source="workday")


def _query_dump(conn, now_iso, label):
    now = datetime.fromisoformat(now_iso)
    from hub.api import _item_of
    upcoming_rows = db.upcoming(conn)
    return {
        "now": now_iso,
        "upcoming": [list(r) for r in upcoming_rows],
        "upcoming_by_category": {
            cat: [list(r) for r in db.upcoming(conn, category=cat)]
            for cat in ("task", "deadline", "material")
        },
        "undated": [list(r) for r in _safe_undated(conn)],
        "courses": [list(r) for r in db.courses(conn)],
        "by_course": {code: [list(r) for r in rows] for code, rows in db.by_course(conn).items()},
        "textbooks": [list(r) for r in db.textbooks(conn)],
        "schedule": [list(r) for r in db.schedule(conn)],
        "status_of_upcoming": [status_of(_item_of(r), now) for r in upcoming_rows],
    }


def _safe_undated(conn):
    # db.undated() INNER JOINs courses - raises if no course row exists at
    # all yet (see hub/db.py). Degrade to [] for a scenario with no courses
    # rather than letting the whole dump fail.
    try:
        return db.undated(conn)
    except Exception:
        return []


def _write_query_golden(case, conn, inputs_note, extra=None):
    # These scenarios are seeded straight from Python Course/Item/Textbook/
    # Meeting objects (exactly like tests/test_db.py etc. do), not from a raw
    # fixture file, so "inputs" stays [] (per tests/parity/superset.py: a
    # non-empty "inputs" entry must resolve under tests/fixtures/) and the
    # human-readable seed description goes under "extra.seed" instead.
    output = {"now_a": _query_dump(conn, NOW_A, "now_a"), "now_b": _query_dump(conn, NOW_B, "now_b")}
    write_json(ORACLE_OUT / "queries" / f"{case}.json", {
        "query": "hub.db.upcoming()/undated()/by_course()/courses()/textbooks()/schedule() + hub.models.status_of()",
        "now": [NOW_A, NOW_B],
        "inputs": [],
        "result": output,
        "extra": {**(extra or {}), "seed": inputs_note},
    })


def harvest_queries():
    conn = db.connect(":memory:")
    db.save(conn, [Q_COURSE], [Q_QUIZ], [Q_BOOK])
    _write_query_golden("basic_save_and_upcoming", conn,
                        ["queries seed: Q_COURSE, Q_QUIZ, Q_BOOK (tests/test_db.py)"])

    conn = db.connect(":memory:")
    reading = Item(course="CPSC 121", category="material", kind="reading", title="Ch. 3",
                  due=datetime(2026, 9, 29, tzinfo=timezone.utc), url="https://x/r/1", source="canvas")
    db.save(conn, [Q_COURSE], [Q_QUIZ, reading])
    _write_query_golden("category_filter", conn,
                        ["queries seed: Q_COURSE, Q_QUIZ (deadline), reading (material)"])

    conn = db.connect(":memory:")
    announcement = Item(course="CPSC 121", category="task", kind="announcement", title="Welcome!",
                        due=None, url="https://x/a/1", source="canvas")
    db.save(conn, [Q_COURSE], [Q_QUIZ, announcement])
    _write_query_golden("undated_vs_upcoming", conn,
                        ["queries seed: Q_COURSE, Q_QUIZ (dated), announcement (undated)"])

    conn = db.connect(":memory:")
    first = Item(course="CPSC 121", category="task", kind="announcement", title="First",
                due=None, url="https://x/a/1", source="canvas")
    second = Item(course="CPSC 121", category="task", kind="announcement", title="Second",
                 due=None, url="https://x/a/2", source="canvas")
    db.save(conn, [Q_COURSE], [first])
    db.save(conn, [Q_COURSE], [second])
    _write_query_golden("undated_most_recent_first", conn,
                        ["queries seed: Q_COURSE, 'First' saved then 'Second' saved separately"])

    conn = db.connect(":memory:")
    essay = Item(course="ENGL 112", category="task", kind="assignment", title="Essay 1",
                due=datetime(2026, 10, 1, tzinfo=timezone.utc), url="https://x/e/1", source="canvas")
    db.save(conn, [Q_COURSE, Q_OTHER_COURSE], [Q_QUIZ, essay])
    _write_query_golden("courses_and_by_course_grouping", conn,
                        ["queries seed: Q_COURSE + Q_OTHER_COURSE, Q_QUIZ + essay"])

    conn = db.connect(":memory:")
    optional_book = Textbook(course="CPSC 121", title="Companion Reader", isbn="999",
                             required=False, price=None, url="")
    db.save(conn, [Q_COURSE], [], [optional_book, Q_BOOK])
    _write_query_golden("textbooks_ordering", conn,
                        ["queries seed: Q_COURSE, optional_book + Q_BOOK (required orders first)"])

    conn = db.connect(":memory:")
    # BRIEF major finding: two adapters writing the same (source, url) -
    # e.g. Canvas's API adapter learning done=True for a quiz, then Canvas's
    # own .ics feed adapter re-saving that same URL with done=None (an .ics
    # feed carries no completion signal at all) - and main's own upsert
    # (hub/db.py) unconditionally does `done=excluded.done`, so the second,
    # less-informed write silently erases the first's real signal. This is
    # oracle-inherited behaviour (not a lauds bug), captured here so lauds'
    # own COALESCE fix (never let a None write clear a known done) has a
    # real golden to diverge from, with evidence.
    done_then_unknown = Item(course="CPSC 121", category="task", kind="quiz", title="Quiz 2",
                             due=datetime(2026, 9, 30, 6, 59, tzinfo=timezone.utc),
                             url="https://x/q/1", source="canvas", done=True)
    done_then_unknown_reupsert = Item(**{**done_then_unknown.__dict__, "done": None})
    db.save(conn, [Q_COURSE], [done_then_unknown])
    db.save(conn, [Q_COURSE], [done_then_unknown_reupsert])
    _write_query_golden("done_clobbered_by_a_later_unknown_write", conn,
                        ["queries seed: Quiz 2 saved done=True, then re-saved (same source+url) done=None"])

    conn = db.connect(":memory:")
    workday_course = Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")
    canvas_item = Item(course="CPSC 121 101 2026W1", category="task", kind="assignment", title="PS3",
                       due=datetime(2026, 9, 28, tzinfo=timezone.utc), url="https://canvas/1", source="canvas")
    db.save(conn, [workday_course], [canvas_item])
    _write_query_golden("canvas_long_code_joins_workday_short_code", conn,
                        ["queries seed: Workday course 'CPSC 121', Canvas item under 'CPSC 121 101 2026W1'"])

    conn = db.connect(":memory:")
    orphan = Item(course="PHIL 100", category="task", kind="assignment", title="Essay",
                 due=datetime(2026, 9, 28, tzinfo=timezone.utc), url="https://x/orphan", source="canvas")
    db.save(conn, [], [orphan])
    _write_query_golden("orphan_item_before_course_known", conn,
                        ["queries seed: item saved with no matching course at all -> '(unknown course)'"])

    conn = db.connect(":memory:")
    quiz3 = Item(course="CPSC 121 101 2026W1", category="deadline", kind="quiz", title="Quiz 3",
                due=datetime(2026, 10, 2, 6, 59, tzinfo=timezone.utc), url="https://canvas.example/quiz/3", source="canvas")
    db.save(conn, [], [quiz3])
    _write_query_golden("orphan_item_before_course_arrives", conn, ["PR33: item saved, course not yet known"])
    db.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                         title="Models of Computation")], [quiz3])
    _write_query_golden("orphan_item_after_course_arrives", conn,
                        ["PR33: same item re-saved once its course is now known -> re-linked, not "
                         "'(unknown course)' forever"])

    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121", section="", term="", title="CPSC 121")])
    db.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026 Winter Term 1",
                         title="Models of Computation", grade=84.0)])
    db.save(conn, [Course(code="CPSC 121", section="101", term="2026W1", title="Models of Computation")])
    _write_query_golden("pr33_term_spellings_join_one_course_row", conn,
                        ["PR33: same course saved 3x under '', '2026 Winter Term 1', '2026W1' -> one row"])

    conn = db.connect(":memory:")
    lecture = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                     title="Models of Computation", grade=84.0)
    lab = Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                title="Models of Computation (Lab)", grade=None)
    db.save(conn, [lecture, lab])
    _write_query_golden("pr33_lab_shell_grade_none_does_not_erase_lecture_grade", conn,
                        ["PR33: lecture (grade=84.0) then lab shell (grade=None), same canonical course"])

    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                         title="Models of Computation"),
                  Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                         title="Models of Computation (Lab)")])
    _write_query_golden("pr33_lecture_then_lab_shorter_title_wins", conn,
                        ["PR33: lecture then lab, both real titles - shorter one wins"])

    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121 L1A 2026W1", section="L1A", term="2026W1",
                         title="Models of Computation (Lab)"),
                  Course(code="CPSC 121 101 2026W1", section="101", term="2026W1",
                         title="Models of Computation")])
    _write_query_golden("pr33_lab_then_lecture_shorter_title_still_wins", conn,
                        ["PR33: same as above, save order reversed - order-independent"])

    conn = db.connect(":memory:")
    db.save(conn, [Course(code="CPSC 121", section="", term=None, title="CPSC 121")])
    _write_query_golden("pr33_none_term_does_not_crash", conn, ["PR33: Course.term=None (Canvas term.name: null)"])

    conn = db.connect(":memory:")
    db.save(conn, [Q_COURSE], meetings=[Q_LECTURE])
    _write_query_golden("schedule_basic", conn, ["queries seed: Q_COURSE + Q_LECTURE"])

    conn = db.connect(":memory:")
    db.save(conn, [Q_COURSE], meetings=[Q_LECTURE])
    moved = Meeting(**{**Q_LECTURE.__dict__, "location": "ICCS 200"})
    db.save(conn, [Q_COURSE], meetings=[moved])
    _write_query_golden("schedule_idempotent_update", conn, ["Q_LECTURE saved, then re-saved with a new location"])

    conn = db.connect(":memory:")
    other_slot = Meeting(**{**Q_LECTURE.__dict__, "days": ["FR"], "start_time": time_cls(9, 0), "end_time": time_cls(10, 0)})
    db.save(conn, [Q_COURSE], meetings=[Q_LECTURE, other_slot])
    _write_query_golden("schedule_second_distinct_time_slot_kept_separately", conn,
                        ["Q_LECTURE plus a second weekly slot at a different time"])

    conn = db.connect(":memory:")
    db.save(conn, [], meetings=[Q_LECTURE])
    _write_query_golden("schedule_meeting_with_unmatched_course_skipped", conn,
                        ["Q_LECTURE saved with no matching course this call -> not orphaned, just skipped"])

    conn = db.connect(":memory:")
    long_code_course = Course(code="CPSC 121 101 2026W1", section="101", term="2026W1", title="Models of Computation")
    db.save(conn, [long_code_course], meetings=[Q_LECTURE])
    _write_query_golden("schedule_canvas_and_workday_join_same_course", conn,
                        ["a meeting saved under Workday's short code, course saved under a longer one"])

    # key_dates round trip (tests/test_key_dates_oracle.py)
    conn = db.connect(":memory:")
    kd_courses, kd_items = key_dates.fetch("UBCV", now=datetime.fromisoformat(NOW_A))
    db.save(conn, kd_courses, kd_items)
    _write_query_golden("key_dates_ubcv_round_trip_after_first_instalment", conn,
                        ["hub.key_dates.fetch('UBCV', now=NOW_A) saved into hub.db - the 1st "
                         "instalment (already passed at NOW_A) must read back done, never overdue"],
                        extra={"first_instalment_due_passed_at": NOW_A})


# ---------------------------------------------------------------------------
# INDEX.md — adapter -> cases -> which main test/behaviour each covers, plus
# a coverage note for behaviours that could NOT be captured offline.
# ---------------------------------------------------------------------------

INDEX_MD = """# Oracle harvest index

Generated by `tools/harvest_oracle.py` against the oracle checkout
(`/sdcard/Projects/helloHacks26`, branch `main`) — read-only, never edited.
Regenerate with:

```
cd /sdcard/Projects/lauds-cli && \\
UV_PROJECT_ENVIRONMENT=/home/.venvs/hub-oracle \\
timeout 300 /home/.venvs/hub-oracle/bin/python tools/harvest_oracle.py
```

Every golden under `tests/oracle/<adapter>/*.json` was produced by calling a
real function in main's `hub` package against a fixture under
`tests/fixtures/<adapter>/` (or a hardcoded literal, itself lifted from a
main test) — never hand-computed. `tests/oracle/queries/*.json` do the same
for `hub.db`'s query functions and `hub.models.status_of`, at two fixed
`now` values (`2026-09-28T09:00:00-07:00`, PDT, and `2026-11-15T09:00:00-08:00`,
PST, after BC's autumn clock change). `tests/oracle/export_ics/*.json` cover
the outbound `.ics` feed and its round trip back through `hub.ics.parse()`.

**`"output"` vs `"result"`** (tests/parity/superset.py's own contract, not
just this file's convention): a golden has exactly one of the two top-level
keys. `"output"` is reserved for a plain `{courses, items, textbooks,
meetings}` record dump — nothing else may appear at that top level (the
comparator's `RECORD_KEYS` check enforces this). Anything whose real return
value carries more than that — `hub.captures.normalize()`'s `source`/`stored`
bookkeeping fields, `hub.export_ics.to_ics()`'s raw `.ics` text plus its
`_uid`/`known_kinds`/`color_for_kind` helpers, and one extension literal
capture that was never itself run through a `parse_capture` (so its `courses`
entries are raw `{ci_id, title}` link data, not real `Course` fields) — uses
`"result"` instead, alongside `"query"` in place of `"oracle_call"`, the same
shape `tests/oracle/queries/*.json` already uses. See `captures/`,
`export_ics/` and `extension/prairielearn_index_capture_literal.json`.

## adapter -> cases -> what each covers

### canvas (`hub/canvas.py`)
- `planner_items_mapping` — tests/test_canvas.py: `test_mapping`,
  `test_calendar_event_url_is_not_double_prefixed`,
  `test_announcement_has_no_due_date`.
- `undated_assignment` — `test_to_undated_item`.
- `done_from_submissions` — `test_done_from_submissions`,
  `test_done_from_submissions_also_honors_the_manual_complete_checkbox`.
- `extension_capture` — `test_extension_capture_uses_the_same_canvas_model_mapping`.
- `extension_js_capture_minimal`, `extension_js_capture_completed` —
  `extension/canvas-capture.test.mjs` (node unavailable on this box; input
  hand-derived from `extension/providers/canvas.js`, output oracle-verified
  through the real `hub.canvas.parse_capture`).
- **Not captured** (not record-shaped / needs live network or monkeypatched
  wiring, not a new mapping behaviour): `unwrap`, the whole OAuth
  authorization/token exchange path, `_BearerRequest`'s origin guard,
  `test_oauth_fetch_reuses_the_canvas_mapping_without_local_browser` (exercises
  wiring already covered by `planner_items_mapping`/`undated_assignment`).

### canvas_ics (`hub/ics.py`'s `parse()`)
- `canvas_feed` — tests/test_ics.py's `FEED`-based tests (kind from UID,
  deep-link rebuild, identity collision fix, all-day Vancouver end-of-day,
  unrecognized UID fallback, bracket-in-title).
- `canvas_feed_as_moodle_source` — `test_no_course_suffix_is_fine`.
- `naive_datetime_gets_vancouver_tz` — `test_naive_datetime_gets_a_timezone_attached`.
- **Not captured**: `fetch`/`fetch_untrusted`/`is_allowed_feed_host`/the feed
  cookie helpers — SSRF/host-allowlist/redirect/size/deadline guards and
  cookie strings, not model records. `to_dict`/`feed_request` are `hub/api.py`
  JSON-endpoint plumbing (thrown out, per BRIEF.md).

### prairielearn (`hub/prairielearn.py`)
- `assessment_rows` — tests/test_prairielearn.py's `to_item` tests (open/not-
  open/closed/closed-but-never-attempted/MST-offset/second-campus).
- `course_title_parsing` — `test_course_title_parsing` + the unparsed-title
  ponytail fallback.
- `parse_capture` — tests/test_experimental_captures.py's
  `test_prairielearn_capture_reuses_live_fixture_mapping`.
- **Not captured**: `resolve_campus`'s whole URL-validation/SSRF-guard surface
  (returns strings/raises, not records), `_course_instances`/`_run`'s HTML
  traversal against fake `_FakeReq` objects (wiring, not a new mapping).

### webwork (`hub/webwork.py`)
- `problem_set_rows` — every `to_item` case in tests/test_webwork.py.
- `two_not_open_sets_distinct_urls` — the synthetic-URL collision regression.
- **Not captured**: `due_from_text`'s standalone parametrised cases (already
  exercised indirectly by `problem_set_rows`; not a distinct record shape).

### workday (`hub/workday.py`)
- `courses_view_my_courses`, `schedule_view_my_courses` — the real anonymised
  export fixture (tests/test_workday.py, tests/test_workday_schedule.py).
- `courses_truncated_dimension` — tests/test_workday_truncated_dimension.py.
- `courses_stray_cell_at_max_address` — tests/test_workday_stray_cell.py.
- `schedule_instructional_format_kind_mapping` — the parametrised
  `test_kind_for_every_known_instructional_format`.
- `schedule_edge_no_recognizable_days`, `schedule_edge_unparseable_time`,
  `schedule_edge_bare_dash`, `schedule_multiple_lines_one_cell`,
  `schedule_no_meeting_patterns_column` — the matching
  tests/test_workday_schedule.py cases.

### bookstore (`hub/bookstore.py`)
- `sections_to_courses` — tests/test_bookstore.py `test_parse_sections` +
  `test_course_from_section_canonicalises_the_bookstores_own_code`, joined.
- `malformed_section_id_fallback` — `test_parse_sections_falls_back_without_crashing_on_a_short_id`.
- `textbooks_cpsc121`, `textbooks_none_listed` — the matching real-fixture tests.
- `textbooks_price_without_cents_and_not_required` — the two synthetic-HTML
  regression tests, combined (same input HTML covers both assertions).
- `attach_store_links` — `test_attach_store_links_scans_the_catalog_once_for_every_book`
  (network calls substituted with the same two fixture pages the real test
  monkeypatches in, not a live hit).
- **Not captured**: `list_terms`/`list_sections`/`isbn_to_store_link`'s network-
  failure-degrades-to-`[]`/`None` behaviour (no record to compare — the whole
  point of those tests is an *empty* result), and `_parse_terms`'s raw dict
  shape (not a shared-model record; `sections_to_courses` covers the
  record-shaped half of the same page).

### key_dates (`hub/key_dates.py`)
- `ubcv_now_a`/`ubcv_now_b`, `ubco_now_a`/`ubco_now_b` — `fetch()` at both
  fixed clocks (tests/test_key_dates.py, tests/test_key_dates_oracle.py).
- `unknown_campus` — `test_unknown_campus_returns_the_course_with_no_dates`.
- See `tests/oracle/queries/key_dates_ubcv_round_trip_after_first_instalment.json`
  for the full db-round-trip + `status_of` behaviour
  (`test_past_key_date_not_overdue_after_hub_db_round_trip`).

### brightspace (`hub/brightspace.py`)
- `to_course_mapping` — tests/test_brightspace.py's `test_to_course_reads_the_real_enrollment_shape`
  + the pagination test's second-page course.
- **Not captured**: `_origin`'s string-normalisation tests (not a record),
  `fetch`'s pagination-following/degrade-to-`([], [])` wiring tests (real
  network shape already fixed by `to_course_mapping`; the wiring itself is a
  monkeypatched-session integration test, not a new mapping behaviour). Items
  are always `[]` — no JSON due-date endpoint exists (module docstring); no
  golden needed for an always-empty list beyond what's already implied.

### moodle / blackboard / piazza (`hub/moodle.py`, `hub/blackboard.py`, `hub/piazza.py`)
- **No dedicated `tests/test_<adapter>.py` exists on `main`** — checked: the
  `tests/` listing has no such files, only inline docstrings marking every
  one of these three `[UNVERIFIED END-TO-END]` (no live account, at UBC or
  anywhere, was ever reached). The only oracle-backed coverage on `main`
  itself is each one's `parse_capture` in tests/test_experimental_captures.py,
  captured here as `moodle/parse_capture`, `blackboard/parse_capture` +
  `blackboard/to_course_missing_term_field`, `piazza/parse_capture_pinned_post`
  + `piazza/parse_capture_non_pinned_dropped_course_number_fallback`. Every
  golden for these three is tagged `"unverified": true` in `extra` — treat
  field-shape parity for these as `fixture-only`, never `live-verified`, until
  someone reaches a real account.

### captures (`hub/captures.py`)
- `normalize_dedupes_by_source_and_url`, `normalize_done_canvas`,
  `normalize_done_prairielearn` — tests/test_captures.py's `normalize()` tests.
  Per-provider `parse_capture` correctness is covered under each provider's
  own adapter section above, not repeated here.
- **Not captured**: the dispatcher's own rejection paths (bad/missing/unverified
  `source`) — errors, not records.

### extension (`extension/providers/*.js`, `extension/*.test.mjs`)
- **`node --version` found nothing on this box** (checked first, per the
  task); every case under `tests/oracle/extension/` was built by hand-tracing
  the relevant provider `.js` source against its own `*.test.mjs` test (noted
  per-case in `extra.note`, `extra.node_available: false`), then piping that
  hand-derived capture through the REAL Python `hub.<source>.parse_capture` —
  only the *input* is hand-derived, every recorded *output* is oracle-verified.
  Covers: PrairieLearn index dedupe (`prairielearn_index_capture_literal`),
  PrairieLearn assessment row field-selection (`prairielearn_assessments_capture_through_parse_capture`),
  Moodle secret-stripping (`moodle_capture_through_parse_capture`), Blackboard
  course-only capture (`blackboard_capture_through_parse_capture`), Piazza
  pinned-post-only capture (`piazza_capture_through_parse_capture`).
- **Not captured**: `background.test.mjs` and `popup.test.mjs` (extension
  message-passing/UI, not provider parsing — out of this task's adapter
  scope), the Canvas capture's *rejection* test (pagination leaving origin —
  an error, not a record; `extension_js_capture_minimal`/`_completed` under
  `tests/oracle/canvas/` already cover the success path end to end).

### export_ics (`hub/export_ics.py`)
- `to_ics_all_items`, `to_ics_filtered_by_kind`, `to_ics_filtered_no_matches`,
  `to_ics_empty_input` — every tests/test_export_ics.py case (round trip
  through `hub.ics.parse`, UID stability/scoping, `CATEGORIES`, `known_kinds`,
  `color_for_kind`).

### queries (`hub/db.py`, `hub/models.status_of`)
- One golden per tests/test_db.py, tests/test_db_schedule.py and
  tests/test_db_oracle_pr33.py scenario (see each file name in `inputs`), plus
  `key_dates_ubcv_round_trip_after_first_instalment` for
  tests/test_key_dates_oracle.py. Each golden dumps `upcoming()` (unfiltered
  and per-category), `undated()`, `courses()`, `by_course()`, `textbooks()`,
  `schedule()` and `status_of()` for every upcoming row, at both fixed `now`
  values.
- **Not captured**: `test_connect_migrates_a_db_from_before_done_existed` (a
  schema-migration regression against a hand-built legacy sqlite file, not a
  query-result golden — nothing for a comparator to diff against another
  adapter's superset), the `Hosted`/Postgres-backed store in `hub/db.py`
  (thrown out per BRIEF.md: `hub/hosted.py` + the Neon store).

## Known gaps (nothing else)

- **Login/session/browser-automation paths** (`hub/site.py`, every adapter's
  `login()`, Playwright-driven `fetch()`) are inherently un-harvestable
  offline; they need a live browser + a live account. Out of scope for this
  task by construction (BRIEF.md: "OFFLINE ORACLE HARVEST").
- **`hub/api.py`, `hub/hosted.py`, `hub/demo.py`, the urgency classifier
  (`hub/models.classify_urgency`, `hub/urgency`-adjacent joblib model), and
  everything under `web/`/`app.py`** are explicitly thrown out per BRIEF.md's
  "Thrown out (do not port)" list — no goldens were harvested for them, even
  where a `main` test exists (e.g. tests/test_urgency.py, tests/test_hosted.py,
  tests/test_demo.py, tests/test_api.py, tests/test_web_normalize.py).
- **moodle/blackboard/piazza**: see the adapter section above — `fixture-only`
  at best, since `main` itself has no live-verified coverage for these three.
"""


def main():
    harvest_canvas()
    harvest_canvas_ics()
    harvest_prairielearn()
    harvest_webwork()
    harvest_workday()
    harvest_bookstore()
    harvest_key_dates()
    harvest_brightspace()
    harvest_moodle()
    harvest_blackboard()
    harvest_piazza()
    harvest_captures()
    harvest_extension()
    harvest_export_ics()
    harvest_queries()

    (ORACLE_OUT / "INDEX.md").write_text(INDEX_MD)
    WRITTEN.append(("index", ORACLE_OUT / "INDEX.md"))

    fixtures_written = sorted({str(p.relative_to(REPO_ROOT)) for kind, p in WRITTEN if kind == "fixture"})
    goldens_written = sorted({str(p.relative_to(REPO_ROOT)) for kind, p in WRITTEN if kind == "golden"})
    print(f"wrote {len(fixtures_written)} fixture files and {len(goldens_written)} golden files")
    print(f"tests/oracle/INDEX.md {'written' if (ORACLE_OUT / 'INDEX.md').exists() else 'MISSING'}")


if __name__ == "__main__":
    main()
