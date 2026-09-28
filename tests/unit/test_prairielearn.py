"""Unit tests ported (behaviourally, not literally) from the oracle's
tests/test_prairielearn.py."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from lauds import session as session_mod
from lauds.adapters.prairielearn import (
    done_from_credit, done_from_score, due_from_popover, looks_logged_out, parse_row,
    resolve_campus, to_course, _course_instances, _get, _run,
)

BASE = "https://us.prairielearn.com"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "prairielearn"

# Real markup captured from a live UBC PrairieLearn course (CPSC 317, 2026W1).
OPEN_ROW = """
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
NOT_OPEN_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">PA2</span></td>
  <td class="align-middle"><span class="text-muted">Implementing a DNS Client</span></td>
  <td class="text-center align-middle"><span class="text-muted">Available 09:00, Mon, Sep 28</span></td>
  <td class="text-center align-middle">Not started</td>
</tr>
"""
CLOSED_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">QUIZ</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/1">Network Delay</a></td>
  <td class="text-center align-middle"></td>
  <td class="text-center align-middle">80%</td>
</tr>
"""
CLOSED_BUT_NEVER_ATTEMPTED_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">PRAC</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/2">Modern Past Due Practice</a></td>
  <td class="text-center align-middle"></td>
  <td class="text-center align-middle">0%</td>
</tr>
"""


def row(html):
    return BeautifulSoup(html, "html.parser").find("tr")


def item(html, course="CPSC 317", group="Programming Assignments", campus_key="prairielearn",
         base=BASE, ci_id="221053"):
    return parse_row(row(html), course_code=course, group=group, campus_key=campus_key, base=base, ci_id=ci_id)


def test_open_assessment_gets_due_from_100pct_tier_and_a_link():
    i = item(OPEN_ROW)
    assert (i.category, i.kind, i.title) == ("task", "assignment", "A Dictionary Client")
    assert i.due.isoformat() == "2026-09-27T23:59:59-07:00"  # PDT, timezone-aware like Canvas's due dates
    assert i.url == "https://us.prairielearn.com/pl/course_instance/221053/assessment_instance/14835025/"


def test_due_is_never_naive():
    assert item(OPEN_ROW).due.tzinfo is not None


def test_not_yet_open_assessment_has_no_due_and_a_fallback_identity_url():
    # A blank url used to mean every unreleased assessment across every
    # course collided onto one row - identity is (source, url).
    i = item(NOT_OPEN_ROW)
    assert i.due is None
    assert i.url == "https://us.prairielearn.com/pl/course_instance/221053/assessments#Implementing%20a%20DNS%20Client"


def test_group_heading_maps_quiz_and_exam():
    assert item(OPEN_ROW, group="Practice for Quizzes").kind == "quiz"
    assert item(OPEN_ROW, group="Formal Quizzes (repeated for practice)").kind == "exam"


def test_last_tier_with_no_end_date_is_none():
    assert due_from_popover(None) is None


def test_a_100_percent_score_is_done():
    assert item(OPEN_ROW).done is True


def test_not_started_is_not_done():
    assert item(NOT_OPEN_ROW).done is False


def test_a_partial_score_is_not_done():
    # Partial credit is still improvable until the assessment closes - only
    # a 100% score means nothing is left to do here.
    partial_row = row(OPEN_ROW.replace('">100%</td>', '">85%</td>'))
    assert done_from_score(partial_row.select("td")) is False


def test_done_from_score_handles_a_short_row_without_crashing():
    assert done_from_score(row(NOT_OPEN_ROW).select("td")[:2]) is None


def test_a_closed_assessment_with_no_available_credit_is_done_even_under_100_percent():
    # The credit schedule fully expired (empty 3rd column) and the score
    # (80%) never reached 100% - done_from_score alone would miss this.
    assert item(CLOSED_ROW, group="Quizzes").done is True


def test_done_from_credit_is_true_only_when_the_column_is_truly_empty():
    assert done_from_credit(row(CLOSED_ROW).select("td")) is True


def test_a_never_attempted_zero_credit_practice_assessment_is_not_done():
    # An empty credit cell alone isn't "done" unless the score is also
    # nonzero (allowSubmissions=true, credit=0 after the last deadline also
    # empties the column, but nothing was ever attempted).
    i = item(CLOSED_BUT_NEVER_ATTEMPTED_ROW, group="Quizzes")
    assert i.done is False
    assert done_from_credit(row(CLOSED_BUT_NEVER_ATTEMPTED_ROW).select("td")) is False
    assert done_from_credit(row(NOT_OPEN_ROW).select("td")) is False  # "Available <time>" notice
    assert done_from_credit(row(OPEN_ROW).select("td")) is False  # still has its popover button


def test_done_from_credit_handles_a_short_row_without_crashing():
    assert done_from_credit(row(NOT_OPEN_ROW).select("td")[:1]) is False


def test_mst_is_a_recognized_offset_alongside_pst_and_pdt():
    i = item(OPEN_ROW.replace("(PDT)", "(MST)"))
    assert i.due.utcoffset().total_seconds() / 3600 == -7


def test_unrecognized_timezone_abbreviation_raises_instead_of_silently_using_utc():
    with pytest.raises(ValueError):
        item(OPEN_ROW.replace("(PDT)", "(XYZ)"))


def test_course_title_parsing():
    c = to_course("221053", "CPSC 317: Internet Computing, 2026 Winter Term 1")
    assert (c.code, c.title, c.term) == ("CPSC 317", "Internet Computing", "2026 Winter Term 1")


def test_course_title_parsing_falls_back_on_unparseable_titles():
    c = to_course("999", "Some unparseable title with no course code")
    assert (c.code, c.title, c.term) == (
        "Some unparseable title with no course code",
        "Some unparseable title with no course code", "")


def test_okanagan_campus_gets_its_own_base_url_and_source():
    # A real student found their assessments live on their school's own
    # PrairieLearn instance, not the shared SaaS one their other courses
    # used - each campus needs its own base URL and its own `source`, so the
    # two never collide under the same (source, url) identity.
    i = item(OPEN_ROW, course="MECH 260", campus_key="prairielearn_ok", base="https://prairielearn.ok.ubc.ca")
    assert i.source == "prairielearn_ok"
    assert i.url == "https://prairielearn.ok.ubc.ca/pl/course_instance/221053/assessment_instance/14835025/"


def test_resolve_campus_known_key():
    assert resolve_campus("prairielearn_ok") == ("prairielearn_ok", "https://prairielearn.ok.ubc.ca")


def test_resolve_campus_pasting_a_known_instances_own_url_resolves_to_its_key():
    assert resolve_campus("https://prairielearn.ok.ubc.ca") == ("prairielearn_ok", "https://prairielearn.ok.ubc.ca")


def test_resolve_campus_accepts_a_pasted_url_for_an_unlisted_instance():
    key, base = resolve_campus("https://pl.autoed.ok.ubc.ca")
    assert (key, base) == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


def test_resolve_campus_strips_a_path_down_to_just_the_host():
    assert resolve_campus("https://pl.autoed.ok.ubc.ca/pl/login") == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


@pytest.mark.parametrize("variant", [
    "https://PL.autoed.OK.ubc.ca",
    "https://pl.autoed.ok.ubc.ca:443",
    "https://pl.autoed.ok.ubc.ca.",
])
def test_resolve_campus_normalises_the_host_before_keying_it(variant):
    assert resolve_campus(variant) == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


@pytest.mark.parametrize("bad", ["http://pl.autoed.ok.ubc.ca", "not a url", "javascript:alert(1)", ""])
def test_resolve_campus_rejects_anything_that_isnt_a_real_https_url(bad):
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://us.prairielearn.com@evil.example",
    "https://user:pass@evil.example",
])
def test_resolve_campus_rejects_userinfo_lookalike_urls(bad):
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://127.0.0.1",
    "https://localhost",
    "https://[::1]",
    "https://192.168.1.1",
])
def test_resolve_campus_rejects_ip_literals_and_localhost(bad):
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://127.1",       # short-form dotted quad
    "https://2130706433",  # pure decimal
    "https://0x7f000001",  # hex
    "https://017700000001",  # octal
    "https://0",            # bare "any address"
])
def test_resolve_campus_rejects_legacy_ipv4_notations_a_browser_would_still_resolve(bad):
    # A browser's URL parser resolves every one of these to a real address
    # (127.0.0.1 or 0.0.0.0) even though ipaddress.ip_address() alone would
    # wave them through as "ordinary hostnames".
    with pytest.raises(ValueError):
        resolve_campus(bad)


class _FakeReq:
    def __init__(self, html):
        self.html = html

    def get(self, url):
        return self

    status = 200
    ok = True

    def text(self):
        return self.html


def test_course_instances_matches_both_student_and_instructor_links():
    html = """
    <a href="/pl/course_instance/1">CPSC 317</a>
    <a href="/pl/course_instance/2/instructor">CPSC 121 (TA)</a>
    """
    assert _course_instances(_FakeReq(html), BASE) == [("1", "CPSC 317"), ("2", "CPSC 121 (TA)")]


class _FakeMultiPageReq:
    def __init__(self, pages, base=BASE):
        self.pages = pages
        self.base = base

    def get(self, url):
        self.html = self.pages[url[len(self.base):]]
        return self

    status = 200
    ok = True

    def text(self):
        return self.html


def test_run_skips_a_course_instance_whose_title_is_not_a_recognisable_course_code():
    # The wider instructor-link matching in _course_instances also picks up
    # PrairieLearn's own built-in example course, whose title doesn't match
    # a course code - it must never surface as a phantom course. No
    # assessments page for id 2 in `pages`: if _run ever fetched it, this
    # test would KeyError instead of just passing.
    pages = {
        "/": """
            <a href="/pl/course_instance/1">CPSC 317: Internet Computing, 2026 Winter Term 1</a>
            <a href="/pl/course_instance/2/instructor">Spring 2015</a>
        """,
        "/pl/course_instance/1/assessments": "<table><tbody></tbody></table>",
    }
    courses, items = _run(_FakeMultiPageReq(pages), "prairielearn", BASE)
    assert [c.code for c in courses] == ["CPSC 317"]


# --- logged-out detection (BRIEF major finding) ------------------------------

def test_looks_logged_out_true_when_the_final_url_is_the_login_page():
    assert looks_logged_out("https://us.prairielearn.com/pl/login")


def test_looks_logged_out_false_for_a_real_page_url():
    assert not looks_logged_out("https://us.prairielearn.com/pl/course_instance/1/assessments")
    assert not looks_logged_out(None)  # a request object with no .url: never flagged this way


class _RedirectedToLoginReq:
    """A request whose response reports the final (post-redirect) URL, like
    Playwright's real APIResponse.url - live-verified: a logged-out GET /
    lands here after following PrairieLearn's own 302."""

    def __init__(self, html):
        self.html = html

    def get(self, url):
        class R:
            status = 200
            ok = True
            url = "https://us.prairielearn.com/pl/login"

            def text(self_):
                return self.html

        return R()


def test_get_raises_not_logged_in_on_the_real_captured_login_redirect_page():
    html = (FIXTURES / "live_loggedout_login_page.html").read_text()
    with pytest.raises(session_mod.NotLoggedIn):
        _get(_RedirectedToLoginReq(html), "/", BASE)
