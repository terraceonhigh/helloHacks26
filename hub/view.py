"""Pure, testable helpers behind the Streamlit UI (#9, #10, #11).

`app.py` should stay UI-only (AGENTS.md), so anything with a return value
worth testing lives here instead of inline in a `with st.tabs(...)` block.

`sort_items`/`flag` below are a stand-in for Sam's hub/logic.py (#2), which
doesn't exist yet. Once it lands, app.py should switch to
`hub.logic.sort_items` / `hub.logic.flag` and these two can go.
"""

from datetime import date, datetime
from itertools import groupby

SOURCE_BADGES = {
    "canvas": "Canvas",
    "ics": "Calendar feed",
    "workday": "Workday",
    "bookstore": "Bookstore",
}


def badge(source):
    """A short, human label for an Item's source, for the badge on each row."""
    return SOURCE_BADGES.get(source, source)


def _due_date(item):
    """An Item's due, normalised to a plain `date` (or None)."""
    due = item.due
    if due is None:
        return None
    return due.date() if isinstance(due, datetime) else due


def sort_items(items):
    """Sort by due date; items with no due date go last."""
    return sorted(items, key=lambda i: (_due_date(i) is None, _due_date(i) or date.max))


def flag(item, today=None):
    """"overdue", "soon" (due within 48h / today, tomorrow, or the day after), or None."""
    due = _due_date(item)
    if due is None:
        return None
    today = today or date.today()
    delta = (due - today).days
    if delta < 0:
        return "overdue"
    if delta <= 2:
        return "soon"
    return None


def group_by_day(items):
    """[(day, [items]), ...] in day order, with one final (None, [...]) bucket
    for items with no due date at all."""
    ordered = sort_items(items)
    dated = [i for i in ordered if _due_date(i) is not None]
    undated = [i for i in ordered if _due_date(i) is None]
    groups = [(day, list(group)) for day, group in groupby(dated, key=_due_date)]
    if undated:
        groups.append((None, undated))
    return groups


def filter_by_course(items, course_code_by_key, picked_codes):
    """Keep items whose mapped course code is one of `picked_codes`.

    An item whose `course_key` doesn't resolve to a known course code at all
    (course_key is None, or -- see hub/ics.py's docstring -- a raw,
    not-yet-normalised course tag from the .ics feed) is always kept: we
    can't tell which course it's for, so the course filter can't rule it
    out. Silently dropping it would hide real data instead of just failing
    to categorise it.
    """
    kept = []
    for item in items:
        code = course_code_by_key.get(item.course_key)
        if code is None or code in picked_codes:
            kept.append(item)
    return kept


def course_summary(course, textbooks):
    """Data for one Course card (#10): required textbooks and their total price."""
    required = [t for t in textbooks if t.course_key == course.key and t.required]
    priced = [t.price_new for t in required if t.price_new is not None]
    return {
        "course": course,
        "required_textbooks": required,
        "required_total": sum(priced) if priced else None,
    }


def mask_secret(value):
    """For on-screen confirmation only -- never show a pasted token/URL in full
    (AGENTS.md rule 3: tokens and .ics feed URLs are passwords)."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]}"
