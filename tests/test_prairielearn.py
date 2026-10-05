import pytest
from bs4 import BeautifulSoup

from hub.prairielearn import (
    done_from_credit, done_from_score, due_from_popover, resolve_campus, to_course, to_item,
    _course_instances, _run,
)

BASE = "https://us.prairielearn.com"

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
# Real markup from the same live course: the credit schedule has fully
# expired (no popover, no "Available" notice - nothing left in that column
# at all), and the score never reached 100%.
CLOSED_ROW = """
<tr>
  <td class="align-middle" style="width: 1%"><span data-testid="assessment-set-badge">QUIZ</span></td>
  <td class="align-middle"><a href="/pl/course_instance/221053/assessment_instance/1">Network Delay</a></td>
  <td class="text-center align-middle"></td>
  <td class="text-center align-middle">80%</td>
</tr>
"""
# Real false positive found in review (#15/#71): allowSubmissions=true,
# credit=0 after the last deadline also empties the credit column, but the
# assessment was never attempted at all - not finished, just no longer
# worth points.
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


def test_open_assessment_gets_due_from_100pct_tier_and_a_link():
    i = to_item(row(OPEN_ROW), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053")
    assert (i.category, i.kind, i.title) == ("task", "assignment", "A Dictionary Client")
    assert i.due.isoformat() == "2026-09-27T23:59:59-07:00"  # PDT, timezone-aware like Canvas's due dates
    assert i.url == "https://us.prairielearn.com/pl/course_instance/221053/assessment_instance/14835025/"


def test_due_is_never_naive():
    # A naive due here would crash any code that compares it against
    # datetime.now(timezone.utc) - e.g. Terrace's "Hide overdue" toggle.
    i = to_item(row(OPEN_ROW), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053")
    assert i.due.tzinfo is not None


def test_not_yet_open_assessment_has_no_due_and_a_fallback_identity_url():
    # A blank url here used to mean every unreleased assessment across every
    # course collided onto one hub.db row, since identity is (source, url).
    i = to_item(row(NOT_OPEN_ROW), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053")
    assert i.due is None
    assert i.url == "https://us.prairielearn.com/pl/course_instance/221053/assessments#Implementing%20a%20DNS%20Client"


def test_group_heading_maps_quiz_and_exam():
    assert to_item(row(OPEN_ROW), "CPSC 317", "Practice for Quizzes", "prairielearn", BASE, "221053").kind == "quiz"
    assert to_item(row(OPEN_ROW), "CPSC 317", "Formal Quizzes (repeated for practice)", "prairielearn", BASE, "221053").kind == "exam"


def test_last_tier_with_no_end_date_is_none():
    assert due_from_popover(None) is None


def test_a_100_percent_score_is_done():
    assert to_item(row(OPEN_ROW), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053").done is True


def test_not_started_is_not_done():
    assert to_item(row(NOT_OPEN_ROW), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053").done is False


def test_a_partial_score_is_not_done():
    # Partial credit is still improvable until the assessment closes - only
    # a 100% score means nothing is left to do here.
    partial_row = row(OPEN_ROW.replace('">100%</td>', '">85%</td>'))
    assert done_from_score(partial_row.select("td")) is False


def test_done_from_score_handles_a_short_row_without_crashing():
    assert done_from_score(row(NOT_OPEN_ROW).select("td")[:2]) is None


def test_a_closed_assessment_with_no_available_credit_is_done_even_under_100_percent():
    # Real shape: the credit schedule fully expired (empty 3rd column), and
    # the score (80%) never reached 100% - done_from_score alone would miss
    # this, since there's nothing left the student can do to change it.
    assert to_item(row(CLOSED_ROW), "CPSC 317", "Quizzes", "prairielearn", BASE, "221053").done is True


def test_done_from_credit_is_true_only_when_the_column_is_truly_empty():
    assert done_from_credit(row(CLOSED_ROW).select("td")) is True


def test_a_never_attempted_zero_credit_practice_assessment_is_not_done():
    # The false positive PM review found: allowSubmissions=true, credit=0
    # after the last deadline also empties the credit column, but nothing
    # was ever attempted - an empty credit cell alone isn't "done" unless
    # the score is also nonzero.
    item = to_item(row(CLOSED_BUT_NEVER_ATTEMPTED_ROW), "CPSC 317", "Quizzes", "prairielearn", BASE, "221053")
    assert item.done is False
    assert done_from_credit(row(CLOSED_BUT_NEVER_ATTEMPTED_ROW).select("td")) is False
    assert done_from_credit(row(NOT_OPEN_ROW).select("td")) is False  # "Available <time>" notice
    assert done_from_credit(row(OPEN_ROW).select("td")) is False  # still has its popover button


def test_done_from_credit_handles_a_short_row_without_crashing():
    assert done_from_credit(row(NOT_OPEN_ROW).select("td")[:1]) is False


def test_mst_is_a_recognized_offset_alongside_pst_and_pdt():
    popover = OPEN_ROW.replace("(PDT)", "(MST)")
    i = to_item(row(popover), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053")
    assert i.due.utcoffset().total_seconds() / 3600 == -7


def test_unrecognized_timezone_abbreviation_raises_instead_of_silently_using_utc():
    popover = OPEN_ROW.replace("(PDT)", "(XYZ)")
    with pytest.raises(ValueError):
        to_item(row(popover), "CPSC 317", "Programming Assignments", "prairielearn", BASE, "221053")


def test_course_title_parsing():
    c = to_course("221053", "CPSC 317: Internet Computing, 2026 Winter Term 1")
    assert (c.code, c.title, c.term) == ("CPSC 317", "Internet Computing", "2026 Winter Term 1")


def test_okanagan_campus_gets_its_own_base_url_and_source():
    # A real student found their MECH 260 assessments live on UBC Okanagan's
    # own PrairieLearn instance, not the shared us.prairielearn.com one -
    # each campus needs its own base URL and its own `source`, so the two
    # never collide under the same (source, url) identity.
    i = to_item(row(OPEN_ROW), "MECH 260", "Programming Assignments", "prairielearn_ok", "https://prairielearn.ok.ubc.ca", "221053")
    assert i.source == "prairielearn_ok"
    assert i.url == "https://prairielearn.ok.ubc.ca/pl/course_instance/221053/assessment_instance/14835025/"


def test_resolve_campus_known_key():
    assert resolve_campus("prairielearn_ok") == ("prairielearn_ok", "https://prairielearn.ok.ubc.ca")


def test_resolve_campus_pasting_a_known_instances_own_url_resolves_to_its_key():
    # A real account connected UBC Okanagan's instance both via the
    # quick-connect button (key "prairielearn_ok") and by pasting its URL
    # directly - without this, the second path produces source
    # "prairielearn.ok.ubc.ca", a different value for the same real
    # instance, so it shows up as two separate connections with duplicated
    # items.
    assert resolve_campus("https://prairielearn.ok.ubc.ca") == ("prairielearn_ok", "https://prairielearn.ok.ubc.ca")


def test_resolve_campus_accepts_a_pasted_url_for_an_unlisted_instance():
    # Any department can self-host their own PrairieLearn (a second, distinct
    # UBC Okanagan instance turned up in the same search that found the
    # first one) - a hardcoded list can never be complete, so a full URL
    # works even when it's not one of the known CAMPUSES keys. The key is
    # "pl-<host>", not the bare host, so a pasted PrairieLearn URL can never
    # collide with another provider's own saved-session/source key (PM
    # review on #56: a pasted "https://canvas" used to overwrite Canvas's).
    key, base = resolve_campus("https://pl.autoed.ok.ubc.ca")
    assert (key, base) == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


def test_resolve_campus_strips_a_path_down_to_just_the_host():
    # A student pasting the login page URL rather than the bare domain
    # shouldn't produce a broken/duplicated base.
    assert resolve_campus("https://pl.autoed.ok.ubc.ca/pl/login") == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


@pytest.mark.parametrize("variant", [
    "https://PL.autoed.OK.ubc.ca",
    "https://pl.autoed.ok.ubc.ca:443",
    "https://pl.autoed.ok.ubc.ca.",
])
def test_resolve_campus_normalises_the_host_before_keying_it(variant):
    # Case, an explicit default port, and a trailing dot are all the same
    # host - each used to make its own separate connection (the exact class
    # of duplicate-connection bug already fixed once for the exact-string
    # case; PM review on #56 wanted it closed for good).
    assert resolve_campus(variant) == ("pl-pl.autoed.ok.ubc.ca", "https://pl.autoed.ok.ubc.ca")


@pytest.mark.parametrize("bad", ["http://pl.autoed.ok.ubc.ca", "not a url", "javascript:alert(1)", ""])
def test_resolve_campus_rejects_anything_that_isnt_a_real_https_url(bad):
    # This opens a real login browser window at whatever's returned - a typo
    # or a non-URL string must fail loudly here, not reach Playwright.
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://us.prairielearn.com@evil.example",
    "https://user:pass@evil.example",
])
def test_resolve_campus_rejects_userinfo_lookalike_urls(bad):
    # A classic look-alike URL: the real-looking hostname before "@" is
    # userinfo, not the host - the browser would actually navigate to
    # evil.example. PM review on #56 found this accepted and navigating.
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://127.0.0.1",
    "https://localhost",
    "https://[::1]",
    "https://192.168.1.1",
])
def test_resolve_campus_rejects_ip_literals_and_localhost(bad):
    # None of these are a real PrairieLearn deployment - PM review on #56
    # found them accepted, which would open the login browser wherever a
    # student's own machine (or an attacker) pointed it.
    with pytest.raises(ValueError):
        resolve_campus(bad)


@pytest.mark.parametrize("bad", [
    "https://127.1",  # short-form dotted quad
    "https://2130706433",  # pure decimal
    "https://0x7f000001",  # hex
    "https://017700000001",  # octal
    "https://0",  # bare "any address"
])
def test_resolve_campus_rejects_legacy_ipv4_notations_a_browser_would_still_resolve(bad):
    # ipaddress.ip_address() only recognizes the canonical dotted-quad/full
    # IPv6 forms - it rejects every one of these as "not an IP", so relying
    # on it alone let them all through as ordinary hostnames. A browser's
    # URL parser (what Playwright actually navigates with) accepts every one
    # of these as an alternate IPv4 notation and resolves it to a real
    # address (each of the 5 above -> 127.0.0.1 or 0.0.0.0) - a real bypass
    # of the same protection the exact-IP test above checks, found on
    # review after #56 landed.
    with pytest.raises(ValueError):
        resolve_campus(bad)


class _FakeReq:
    def __init__(self, html):
        self.html = html

    def get(self, url):
        return self

    @property
    def status(self):
        return 200

    @property
    def ok(self):
        return True

    def text(self):
        return self.html


def test_course_instances_matches_both_student_and_instructor_links():
    html = """
    <a href="/pl/course_instance/1">CPSC 317</a>
    <a href="/pl/course_instance/2/instructor">CPSC 121 (TA)</a>
    """
    assert _course_instances(_FakeReq(html), BASE) == [("1", "CPSC 317"), ("2", "CPSC 121 (TA)")]


class _FakeMultiPageReq:
    """Routes by path, keyed the way _get_soup builds them (base + path)."""

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


def test_run_skips_a_course_instance_whose_title_is_not_a_ubc_course_code():
    # The wider instructor-link matching in _course_instances also picks up
    # PrairieLearn's own built-in example course, whose title doesn't match a
    # UBC course code - it used to come through as a phantom "Spring 2015"
    # course (#15). No assessments page for id 2 in `pages`: if _run ever
    # fetched it, this test would KeyError instead of just passing.
    pages = {
        "/": """
            <a href="/pl/course_instance/1">CPSC 317: Internet Computing, 2026 Winter Term 1</a>
            <a href="/pl/course_instance/2/instructor">Spring 2015</a>
        """,
        "/pl/course_instance/1/assessments": "<table><tbody></tbody></table>",
    }
    courses, items = _run(_FakeMultiPageReq(pages), "prairielearn", BASE)
    assert [c.code for c in courses] == ["CPSC 317"]
