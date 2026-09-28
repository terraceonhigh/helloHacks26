"""Behavioural port of main's tests/test_brightspace.py onto
lauds.adapters.brightspace - same enrollment shape (anonymised copy of a real
UBC course response, checked live 2026-09-26), same assertions."""
from lauds.adapters import brightspace
from lauds.models import Course

ENROLLMENTS_RESPONSE = {
    "PagingInfo": {"Bookmark": "12345", "HasMoreItems": False},
    "Items": [
        {
            "OrgUnit": {
                "Id": 12345,
                "Type": {"Id": 3, "Code": "Course Offering", "Name": "Course Offering"},
                "Name": "MATH_V 100A ALL SECTIONS 2026W1 Differential Calculus with Applications",
                "Code": "MATH_V 100A ALL SECTIONS 2026W1",
                "HomeUrl": "https://example.brightspace.com/d2l/home/12345",
            },
            "Access": {"IsActive": True},
            "PinDate": None,
        }
    ],
}


def test_origin_passes_through_a_bare_origin_unchanged():
    assert brightspace._origin("https://ubc.brightspace.com") == "https://ubc.brightspace.com"


def test_origin_strips_a_full_course_url_down_to_just_the_origin():
    assert brightspace._origin("https://ubc.brightspace.com/d2l/home/7067") == "https://ubc.brightspace.com"


def test_to_course_reads_the_real_enrollment_shape():
    course = brightspace.to_course(ENROLLMENTS_RESPONSE["Items"][0])
    assert isinstance(course, Course)
    assert course.code == "MATH_V 100A ALL SECTIONS 2026W1"
    assert course.title == "MATH_V 100A ALL SECTIONS 2026W1 Differential Calculus with Applications"
    assert course.section == ""  # no section/term field exists in this response
    assert course.term == ""
    assert course.source == "brightspace"


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status
        self.ok = status < 400

    def text(self):
        import json
        return json.dumps(self._payload)


class _FakeRequest:
    def __init__(self, pages_by_url):
        self.pages_by_url = pages_by_url
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url.endswith("/whoami"):
            return _FakeResponse({"Identifier": "1"})
        for suffix, page in self.pages_by_url.items():
            if url.endswith(suffix) or suffix in url:
                return _FakeResponse(page)
        raise AssertionError(f"unexpected url {url!r}")


def test_fetch_returns_courses_from_enrollments_and_no_items(monkeypatch):
    req = _FakeRequest({"orgUnitTypeId=3": ENROLLMENTS_RESPONSE})
    monkeypatch.setattr(brightspace.session, "fetch_with_session",
                         lambda site_name, base, run: run(req))
    bundle = brightspace.fetch("https://example.brightspace.com")
    assert [c.code for c in bundle.courses] == ["MATH_V 100A ALL SECTIONS 2026W1"]
    assert bundle.items == []
    assert any("whoami" in c for c in req.calls)
    assert any("enrollments" in c for c in req.calls)


def test_fetch_normalises_a_full_course_url_to_the_origin(monkeypatch):
    req = _FakeRequest({"orgUnitTypeId=3": ENROLLMENTS_RESPONSE})
    seen_bases = []

    def fake_fetch_with_session(site_name, base, run):
        seen_bases.append(base)
        return run(req)

    monkeypatch.setattr(brightspace.session, "fetch_with_session", fake_fetch_with_session)
    bundle = brightspace.fetch("https://example.brightspace.com/d2l/home/7067")
    assert seen_bases == ["https://example.brightspace.com"]
    assert [c.code for c in bundle.courses] == ["MATH_V 100A ALL SECTIONS 2026W1"]


def test_fetch_follows_pagination_across_multiple_enrollment_pages(monkeypatch):
    page1 = {
        "PagingInfo": {"Bookmark": "111", "HasMoreItems": True},
        "Items": [ENROLLMENTS_RESPONSE["Items"][0]],
    }
    second_course = {"OrgUnit": {"Id": 222, "Name": "A Second Course", "Code": "SECOND 200"},
                      "Access": {"IsActive": True}, "PinDate": None}
    page2 = {"PagingInfo": {"Bookmark": None, "HasMoreItems": False}, "Items": [second_course]}

    class _PagedRequest:
        def get(self, url):
            if url.endswith("/whoami"):
                return _FakeResponse({"Identifier": "1"})
            if "bookmark=" in url:
                return _FakeResponse(page2)
            return _FakeResponse(page1)

    monkeypatch.setattr(brightspace.session, "fetch_with_session",
                         lambda site_name, base, run: run(_PagedRequest()))
    bundle = brightspace.fetch("https://example.brightspace.com")
    assert [c.code for c in bundle.courses] == ["MATH_V 100A ALL SECTIONS 2026W1", "SECOND 200"]


def test_fetch_raises_rather_than_swallow_a_failure(monkeypatch):
    # Unlike main (which caught everything into ([], [])), lauds lets a
    # failure propagate - lauds.sync isolates one broken adapter from the
    # rest at the sync layer (lauds/sync.py:sync_one), not inside fetch().
    def fake_fetch_with_session(site_name, base, run):
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(brightspace.session, "fetch_with_session", fake_fetch_with_session)
    try:
        brightspace.fetch("https://example.brightspace.com")
    except RuntimeError as e:
        assert "simulated" in str(e)
    else:
        raise AssertionError("expected RuntimeError to propagate")
