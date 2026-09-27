"""Network-free: replay pages captured from the real PrairieLearn server through the adapter."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

from fusion.adapters import prairielearn as pl

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "prairielearn"
INDEX = json.loads((FIX / "index.json").read_text())
BASE = INDEX["base"]
VAN = ZoneInfo("America/Vancouver")


class FakeResponse:
    def __init__(self, url, status, text):
        self.url, self.status_code, self.text = url, status, text
        self.ok = status < 400

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code} {self.url}")


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        page = INDEX["pages"].get(urlparse(url).path)
        if page is None:
            return FakeResponse(url, 404, "")
        return FakeResponse(url, page["status"], (FIX / page["file"]).read_text())


@pytest.fixture(scope="module")
def fetched():
    s = FakeSession()
    return pl.fetch(s, BASE), s


def van(*t):
    return datetime(*t, tzinfo=VAN)


def test_course(fetched):
    snap, _ = fetched
    assert snap.source == "prairielearn"
    (c,) = snap.courses
    assert c.label == "CPSC 121, 2026W1"
    assert c.title == "CPSC 121: Models of Computation, 2026 Winter Term 1"
    assert c.term_hint == "2026 Winter Term 1"
    assert c.url == f"{BASE}/pl/course_instance/{c.source_id}"


@pytest.mark.parametrize("title,kind,label,due,opens", [
    ("Quiz 1", "quiz", "Q1", van(2026, 10, 2, 23, 59), van(2026, 9, 1)),
    ("Problem Set 3", "homework", "PS3", van(2026, 10, 5, 17, 0), van(2026, 9, 1)),
    ("Quiz 2", "quiz", "Q2", van(2026, 10, 16, 23, 59), van(2026, 9, 1)),
    ("Lab 4", "lab", "L4", van(2026, 10, 27, 23, 59), van(2026, 10, 20)),
])
def test_scenario_items(fetched, title, kind, label, due, opens):
    snap, _ = fetched
    (it,) = [i for i in snap.items if i.title == title]
    ci = snap.courses[0].source_id
    assert it.kind == kind
    assert it.source_id == f"{ci}:{label}" and it.course_source_id == ci
    assert it.due == due and it.opens == opens
    for d in (it.due, it.opens):
        assert d.tzinfo is not None and d.utcoffset() == timedelta(hours=-7) and d.tzname() == "PDT"
    assert it.links_out == ()
    assert it.url.startswith(f"{BASE}/pl/course_instance/{ci}/")


def test_exactly_the_scenario_items(fetched):
    snap, _ = fetched
    assert sorted(i.title for i in snap.items) == ["Lab 4", "Problem Set 3", "Quiz 1", "Quiz 2"]


def test_urls(fetched):
    snap, _ = fetched
    by = {i.title: i for i in snap.items}
    ci = snap.courses[0].source_id
    # Exam-type quizzes: the assessment's own page (a "Start assessment" page, no side effect).
    assert "/assessment/" in by["Quiz 1"].url and "/assessment/" in by["Quiz 2"].url
    assert by["Quiz 1"].url != by["Quiz 2"].url
    # The oracle clicked the homework, so the student's list now links their instance.
    assert "/assessment_instance/" in by["Problem Set 3"].url
    # Not open yet: PL shows no link, so the adapter falls back to the list and says so.
    assert by["Lab 4"].url == f"{BASE}/pl/course_instance/{ci}/assessments#L4"
    assert any("Lab 4" in n for n in snap.notes)


def test_never_gets_unstarted_assessment_pages(fetched):
    # GET /assessment/<id>/ on a Homework creates an instance: the adapter must not do it.
    _, s = fetched
    assert not any("/assessment/" in urlparse(u).path for u in s.calls)


def test_parse_pl_date_honours_printed_zone():
    assert pl.parse_pl_date("2026-10-02 23:59:00 (PDT)") == datetime(2026, 10, 3, 6, 59, tzinfo=timezone.utc)
    # After the BC change the server prints PST; trust it.
    assert pl.parse_pl_date("2027-01-15 23:59:00 (PST)").utcoffset() == timedelta(hours=-8)
    assert pl.parse_pl_date("2026-10-02 23:59:00 (GMT+5:30)").utcoffset() == timedelta(hours=5, minutes=30)
    # Unknown abbreviation: only accepted if the display zone prints it at that instant.
    assert pl.parse_pl_date("2026-07-01 12:00:00 (CEST)") is None
    assert pl.parse_pl_date("2026-07-01 12:00:00 (CEST)", "Europe/Berlin").utcoffset() == timedelta(hours=2)
    assert pl.parse_pl_date("—") is None


def test_external_links_keep_same_host_other_port_and_skip_typos():
    page = ('<main><a href="http://127.0.0.1:8082/mod/assign/view.php?id=10">m</a> '
            '<a href="http://127.0.0.1:8081/webwork2/math100_2026w1/HW2/">w</a> '
            '<a href="/pl/course_instance/1/assessment/3/">own</a> '
            '<a href="http://127.0.0.1:3100/pl/x">own abs</a> '
            '<a href="http://[bad/x">typo</a> <a href="http://h:99999/x">typo2</a></main>')
    assert pl._external_links(page, "http://127.0.0.1:3100") == (
        "http://127.0.0.1:8082/mod/assign/view.php?id=10",
        "http://127.0.0.1:8081/webwork2/math100_2026w1/HW2/")
    assert pl._external_links('<main><a href="https://pl.test:443/a">x</a></main>', "https://pl.test") == ()
