"""Shared model every adapter returns. Keep it tiny (see issue #1)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

Category = Literal["task", "deadline", "material"]

# What bucket a given kind falls into. Adapters pick a specific `kind`
# ("assignment", "quiz", "reading", ...); this decides which of the three
# lists (tasks / deadlines-and-key-dates / materials) it shows up in.
# Unlisted kinds default to "task" - the safest bucket for "something to deal with".
CATEGORY_FOR: dict[str, Category] = {
    "assignment": "task",
    "announcement": "task",
    "quiz": "deadline",
    "exam": "deadline",
    "event": "deadline",  # calendar events: breaks, key dates, office hours
    "break": "deadline",
    "payment": "deadline",  # e.g. tuition due
    "reading": "material",
    "textbook": "material",
}


def category_for(kind: str) -> Category:
    return CATEGORY_FOR.get(kind, "task")


@dataclass
class Course:
    code: str
    section: str
    term: str
    title: str
    grade: float | None = None  # current score %, Canvas only


@dataclass
class Item:
    course: str
    category: Category
    kind: str  # specific label within the category, e.g. "quiz", "reading" - free-form, new providers can add one without touching this file
    title: str
    due: datetime | None  # always tz-aware if set - never mix naive and aware across adapters
    url: str
    source: str
    done: bool | None = None  # completed/submitted, if the source can tell us. None = unknown/not applicable


Status = Literal["done", "overdue", "soon", "upcoming"]
SOON_WINDOW = timedelta(hours=48)  # matches docs/design.md's "due-in-48h" pinning/amber rule


def status_of(item: Item, now: datetime | None = None) -> Status:
    """Where an item sits right now. Never stored - "overdue"/"soon" are pure
    functions of `due` vs `now`, recomputed on every read (hub.db doesn't
    persist this), so it's never stale."""
    now = now or datetime.now(timezone.utc)
    if item.done:
        return "done"
    if item.due is None:
        return "upcoming"
    if item.due < now:
        return "overdue"
    if item.due - now <= SOON_WINDOW:
        return "soon"
    return "upcoming"


@dataclass
class Textbook:
    course: str
    title: str
    isbn: str
    required: bool
    price: float | None
    url: str
