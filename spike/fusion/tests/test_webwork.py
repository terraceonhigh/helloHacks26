"""Network-free: replay raw WeBWorK responses (captured from the real server by
oracles/webwork_oracle.py --save-fixtures) through the adapter."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fusion import snapshot_io
from fusion.adapters import webwork

FX = Path(__file__).resolve().parent.parent / "fixtures" / "webwork"
PDT = timezone(timedelta(hours=-7))
PST = timezone(timedelta(hours=-8))
COURSE = "math100_2026w1"


class Resp:
    def __init__(self, text, status, url):
        self.text, self.status_code, self.url = text, status, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, patch=None):
        m = json.loads((FX / "manifest.json").read_text())
        self.base = m["base"]
        self.responses = m["responses"]
        self.patch = patch or {}

    def get(self, url, **kw):
        e = self.responses[url]
        text = (FX / e["file"]).read_text()
        if url in self.patch:
            text = self.patch[url](text)
        return Resp(text, e["status"], e["final_url"])


@pytest.fixture(scope="module")
def snap():
    s = FakeSession()
    return webwork.fetch(s, s.base)


def _item(snap, set_id):
    return next(i for i in snap.items if i.source_id == f"{COURSE}/{set_id}")


def test_course(snap):
    assert [(c.source, c.source_id, c.label) for c in snap.courses] == [("webwork", COURSE, COURSE)]
    assert snap.courses[0].url.endswith(f"/webwork2/{COURSE}")


def test_exactly_the_scenario_sets(snap):
    assert sorted(i.title for i in snap.items) == ["HW1", "HW2", "HW3", "HW9"]
    assert snap.notes == ()


@pytest.mark.parametrize("set_id,due,opens", [
    ("HW1", datetime(2026, 9, 20, 23, 59, tzinfo=PDT), None),                                  # W1 past due
    ("HW2", datetime(2026, 9, 29, 23, 59, tzinfo=PDT), None),                                  # W2 open
    ("HW9", datetime(2027, 1, 15, 23, 59, tzinfo=PST), datetime(2026, 12, 1, 0, 0, tzinfo=PST)),  # W3
    ("HW3", datetime(2026, 10, 17, 23, 59, tzinfo=PDT), datetime(2026, 10, 10, 0, 0, tzinfo=PDT)),  # W4 not open
])
def test_scenario_items(snap, set_id, due, opens):
    it = _item(snap, set_id)
    assert it.source == "webwork" and it.course_source_id == COURSE
    assert it.kind == "homework"
    assert it.due == due and it.due.utcoffset() == due.utcoffset()
    assert it.opens == opens
    if opens:
        assert it.opens.utcoffset() == opens.utcoffset()
    assert it.url == f"{snap.base.rstrip('/')}/webwork2/{COURSE}/{set_id}"
    assert it.submit_url is None and it.links_out == ()


def test_hw9_keeps_printed_pst_not_os_zone(snap):
    # WeBWorK printed "PST" (UTC-8) for Jan 2027; newer tzdata says BC is UTC-7 then.
    assert _item(snap, "HW9").due == datetime(2027, 1, 16, 7, 59, tzinfo=timezone.utc)


def test_saved_snapshot_matches_replay(snap):
    saved = snapshot_io.load(FX.parent / "snapshots" / "webwork.json")
    assert saved.items == snap.items and saved.courses == snap.courses


def test_custom_header_gives_undated_plus_note():
    # An instructor-replaced set header hides the due date of a past-due set.
    s = FakeSession()
    url = next(u for u in s.responses if u.endswith("/HW1"))
    s.patch[url] = lambda t: t.replace("This assignment will close on", "Have fun with")
    snap = webwork.fetch(s, s.base)
    assert _item(snap, "HW1").due is None
    assert any("HW1" in n for n in snap.notes)


def test_course_url_base():
    s = FakeSession()
    snap = webwork.fetch(s, f"{s.base}/webwork2/{COURSE}")
    assert len(snap.items) == 4


@pytest.mark.parametrize("text,expected", [
    ("Open. Due September 29, 2026, 11:59:00 PM PDT.", datetime(2026, 9, 29, 23, 59, tzinfo=PDT)),
    ("closes on 01/15/2027 ... January 15, 2027 at 11:59pm PST", datetime(2027, 1, 15, 23, 59, tzinfo=PST)),
    ("Due March 3, 2027, 12:05:00 AM -0700", datetime(2027, 3, 3, 0, 5, tzinfo=PDT)),
    ("Due March 3, 2027, 12:00:00 PM UTC", datetime(2027, 3, 3, 12, 0, tzinfo=timezone.utc)),
    ("Answers available for review.", None),
])
def test_parse_date(text, expected):
    got = webwork.parse_date(text)
    assert got == expected
    if got:
        assert got.utcoffset() == expected.utcoffset()


def test_unknown_zone_refused():
    with pytest.raises(webwork.ZoneUnknown):
        webwork.parse_date("Due March 3, 2027, 12:00:00 PM IST")


def test_links_out_survives_broken_urls():
    from bs4 import BeautifulSoup
    el = BeautifulSoup('<div><a href="http://[bad/x">b</a> http://[bad/y '
                       '<a href="http://localhost:8082/mod/assign/view.php?id=3">m</a></div>', "html.parser")
    assert webwork._links_out(el, "http://localhost:8081/webwork2/c/HW2/") == [
        "http://localhost:8082/mod/assign/view.php?id=3"]
