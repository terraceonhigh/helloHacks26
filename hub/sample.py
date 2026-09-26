"""Load the fake data in fixtures/ as shared-model objects, for the UI and tests."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from hub.models import Course, Item, Textbook

FIXTURES = Path(__file__).parent.parent / "fixtures"

# fixtures/items.json is written around the week starting on this Monday.
SAMPLE_WEEK = date(2026, 9, 28)


def _read(name):
    return json.loads((FIXTURES / name).read_text())


def load_sample(today=None):
    """Return (courses, items, textbooks) from fixtures/.

    Item due dates are moved forward by whole weeks so the sample week lines up
    with the week containing `today`. That keeps the demo looking "live".
    Pass today=SAMPLE_WEEK to get the dates exactly as written.
    """
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    shift = timedelta(weeks=(this_monday - SAMPLE_WEEK).days // 7)

    courses = [Course(**c) for c in _read("courses.json")]
    items = []
    for raw in _read("items.json"):
        raw["due"] = datetime.fromisoformat(raw["due"]) + shift if raw["due"] else None
        items.append(Item(**raw))
    textbooks = [Textbook(**t) for t in _read("textbooks.json")]
    return courses, items, textbooks
