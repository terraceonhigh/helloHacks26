"""Pure functions on the shared model: sort/rank items. Nothing here touches
SQL or a provider - see hub/db.py and hub/<provider>.py for those.

sort_items() is design.md's "Ranking" section: an urgency function replaces
the plain due-date sort behind the same call, so the UI doesn't change.
classify_urgency() (hub/models.py) is the stand-in for the weight-based
formula there until Item carries a real weight field.
"""
from datetime import datetime

from hub.models import classify_urgency

_URGENCY_ORDER = ("overdue", "critical", "high", "medium", "low")


def sort_items(rows, now=None, urgency_fn=classify_urgency):
    """Sort hub.db.upcoming() rows - (code, category, kind, title, due, url,
    done) - most urgent first. Ties break by due date. `urgency_fn` defaults
    to the rule-based classifier; pass hub.urgency_model.predict_urgency to
    sort by the trained model instead (same (title, due, now) signature)."""

    def key(row):
        due = datetime.fromisoformat(row[4])
        return (_URGENCY_ORDER.index(urgency_fn(row[3], due, now)), due)

    return sorted(rows, key=key)
