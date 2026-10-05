"""Oracle for PR #37 (hub/key_dates.py) - network-free, fixed clock.

Reviewer finding (a): once 2026-09-09 passes, the "Tuition: 1st instalment
due" item reports status_of(...) == "overdue" for EVERY student. That's a
false alarm: most students have paid, and Hub has no way to know (there's no
login to the fees system behind this provider - it's public, same for all).

PROPOSAL for Jacky (expected behaviour this oracle encodes):
  A public key date whose time has passed is "done" - the existing Status
  that already means "nothing left to act on here" and that app.py and
  hub.api already hide. No new status name. Before the date it behaves
  like any other deadline ("upcoming"/"soon"), so the reminder still shows.
  The mechanism is Jacky's call (e.g. fetch() setting Item.done for elapsed
  dates, or dropping them); the oracle only pins behaviour, and checks it
  survives a hub.db round trip, because that's the path the UI actually
  reads (note hub.api._item_of rebuilds Items with source="", so a fix
  keyed on `source` alone would not reach the UI).

Clock: FIXED_AFTER / FIXED_BEFORE are injected both into status_of(now=...)
and into fetch() - via a `now=` kwarg if fetch grows one, else by freezing
hub.key_dates.datetime.now - so the result never depends on today's date.
"""
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import hub.key_dates as key_dates
from hub import db
from hub.api import _item_of
from hub.models import status_of

VAN = ZoneInfo("America/Vancouver")
FIXED_AFTER = datetime(2026, 9, 26, 12, 0, tzinfo=VAN)   # 1st instalment passed, 2nd not yet
FIXED_BEFORE = datetime(2026, 9, 1, 12, 0, tzinfo=VAN)   # both still ahead
FIRST = "Tuition: 1st instalment due (Winter Session)"
SECOND = "Tuition: 2nd instalment due (Winter Session)"


def _frozen_datetime(now):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)
    return Frozen


def _fetch_at(monkeypatch, now, campus="UBCV"):
    if isinstance(getattr(key_dates, "datetime", None), type):
        monkeypatch.setattr(key_dates, "datetime", _frozen_datetime(now))
    if "now" in inspect.signature(key_dates.fetch).parameters:
        return key_dates.fetch(campus, now=now)
    return key_dates.fetch(campus)


def _by_title(items):
    return {i.title: i for i in items}


@pytest.mark.parametrize("campus", sorted(key_dates.KEY_DATES))
def test_past_key_date_is_not_reported_overdue(monkeypatch, campus):
    _, items = _fetch_at(monkeypatch, FIXED_AFTER, campus)
    first = _by_title(items)[FIRST]
    assert first.due < FIXED_AFTER  # precondition: the date really has passed
    assert status_of(first, FIXED_AFTER) != "overdue", (
        "a public key date Hub can't track per-student must not alarm as overdue once past")


def test_proposed_past_key_date_is_done_and_future_one_still_shows(monkeypatch):
    _, items = _fetch_at(monkeypatch, FIXED_AFTER)
    by = _by_title(items)
    assert status_of(by[FIRST], FIXED_AFTER) == "done"
    assert status_of(by[SECOND], FIXED_AFTER) == "upcoming"


def test_key_date_before_it_passes_is_a_normal_reminder(monkeypatch):
    _, items = _fetch_at(monkeypatch, FIXED_BEFORE)
    assert status_of(_by_title(items)[FIRST], FIXED_BEFORE) in ("upcoming", "soon")


def test_past_key_date_not_overdue_after_hub_db_round_trip(monkeypatch):
    # The UI (app.py, hub.api) never sees fetch()'s Items directly - it reads
    # rows back out of hub.db. The fix has to survive that.
    conn = db.connect(":memory:")
    db.save(conn, *_fetch_at(monkeypatch, FIXED_AFTER))
    rows = [r for r in db.upcoming(conn) if r[3] == FIRST]
    assert rows, "key date row missing from hub.db"
    assert status_of(_item_of(rows[0]), FIXED_AFTER) != "overdue"


@pytest.mark.parametrize("campus", sorted(key_dates.KEY_DATES))
def test_every_due_is_tz_aware_america_vancouver(campus):
    # Jacky's standard #3 (tz-aware) + the right zone: the offset must be
    # Vancouver's actual offset at that wall-clock time (PDT -07 in Sept,
    # PST -08 in Jan), so a DST-wrong hand-typed offset is caught.
    _, items = key_dates.fetch(campus)
    assert items
    for item in items:
        assert item.due.tzinfo is not None and item.due.utcoffset() is not None, item.title
        wall = item.due.replace(tzinfo=None)
        assert item.due.utcoffset() == wall.replace(tzinfo=VAN).utcoffset(), (
            f"{item.title}: offset {item.due.utcoffset()} isn't America/Vancouver's on {wall:%Y-%m-%d}")
