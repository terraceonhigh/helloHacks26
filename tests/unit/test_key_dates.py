"""Behaviour ported from main's tests/test_key_dates.py and
tests/test_key_dates_oracle.py (not literal copies) - against
lauds.adapters.key_dates, which takes `now` as a real argument throughout
rather than needing a frozen-clock monkeypatch."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lauds.adapters import key_dates
from lauds.models import status_of

VAN = ZoneInfo("America/Vancouver")
FIXED_AFTER = datetime(2026, 9, 26, 12, 0, tzinfo=VAN)   # 1st instalment passed, 2nd not yet
FIXED_BEFORE = datetime(2026, 9, 1, 12, 0, tzinfo=VAN)   # both still ahead
FIRST = "Tuition: 1st instalment due (Winter Session)"
SECOND = "Tuition: 2nd instalment due (Winter Session)"


def _fetch(campus="UBCV", now=FIXED_BEFORE):
    return key_dates.fetch(campus=campus, term="2026W1", now=now)


def _by_title(items):
    return {i.title: i for i in items}


def test_fetch_returns_a_course_and_dated_items():
    bundle = _fetch()
    assert bundle.courses[0].code == "UBCV"
    assert len(bundle.items) >= 1
    assert all(item.due is not None for item in bundle.items)
    assert all(item.category == "deadline" for item in bundle.items)  # "payment" -> category_for -> "deadline"


def test_unknown_campus_returns_the_course_with_no_dates():
    bundle = _fetch(campus="MARS_U")
    assert bundle.courses[0].code == "MARS_U"
    assert bundle.items == []


def test_items_have_distinct_urls_so_they_dont_collide_by_identity():
    # Two entries sharing a url would collide on the (source, url) identity
    # every item is matched on and silently overwrite each other.
    urls = [item.url for item in _fetch().items]
    assert len(urls) == len(set(urls))


def test_every_campus_shares_the_same_shape():
    for campus in key_dates.KEY_DATES:
        bundle = _fetch(campus=campus)
        assert bundle.courses[0].code == campus
        assert len(bundle.items) == len(key_dates.KEY_DATES[campus])


@pytest.mark.parametrize("campus", sorted(key_dates.KEY_DATES))
def test_past_key_date_is_not_reported_overdue(campus):
    items = _fetch(campus=campus, now=FIXED_AFTER).items
    first = _by_title(items)[FIRST]
    assert first.due < FIXED_AFTER  # precondition: the date really has passed
    assert status_of(first, FIXED_AFTER) != "overdue", (
        "a public key date lauds can't track per-student must not alarm as overdue once past")


def test_past_key_date_is_done_and_future_one_still_shows():
    by = _by_title(_fetch(now=FIXED_AFTER).items)
    assert status_of(by[FIRST], FIXED_AFTER) == "done"
    assert status_of(by[SECOND], FIXED_AFTER) == "upcoming"


def test_key_date_before_it_passes_is_a_normal_reminder():
    by = _by_title(_fetch(now=FIXED_BEFORE).items)
    assert status_of(by[FIRST], FIXED_BEFORE) in ("upcoming", "soon")


@pytest.mark.parametrize("campus", sorted(key_dates.KEY_DATES))
def test_every_due_is_tz_aware_america_vancouver(campus):
    # The offset must be Vancouver's actual offset at that wall-clock time
    # (PDT -07 in Sept, PST -08 in Jan), so a DST-wrong hand-typed offset
    # would be caught.
    items = _fetch(campus=campus).items
    assert items
    for item in items:
        assert item.due.tzinfo is not None and item.due.utcoffset() is not None, item.title
        wall = item.due.replace(tzinfo=None)
        assert item.due.utcoffset() == wall.replace(tzinfo=VAN).utcoffset(), (
            f"{item.title}: offset {item.due.utcoffset()} isn't America/Vancouver's on {wall:%Y-%m-%d}")


def test_fetch_defaults_now_to_the_real_clock():
    # No now= at all still returns a usable bundle - status_of is a pure
    # function of the read, not of when fetch() itself ran.
    bundle = key_dates.fetch(campus="UBCV")
    assert bundle.items
