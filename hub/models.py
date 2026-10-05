"""Shared model every adapter returns. Keep it tiny (see issue #1)."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
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
class ItemFile:
    """One thing attached to an Item - a reading, a template, a folder of
    course notes - for the mockup's Finder-style files pane (#26/#38's
    dashboard sketch). `kind` picks the icon; `folder` has no direct
    download, just groups files under it."""
    name: str
    url: str
    kind: Literal["file", "folder", "link"] = "file"


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
    # ponytail: no adapter populates this yet - whether it's an LLM agent or
    # a per-provider heuristic that fills it in is Terrace's open question on
    # #26/#38, not decided here. This only settles the shape: [] (the
    # default) means "not fetched", not "genuinely no files".
    files: list[ItemFile] = field(default_factory=list)


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


Urgency = Literal["overdue", "critical", "high", "medium", "low"]

# Keyword -> inferred grade weight, when Item has no explicit weight field yet
# (see docs/design.md's urgency formula). First match wins; order matters.
# ponytail: keyword list, not an NLP model - a hackathon demo doesn't have
# training data to justify one. Upgrade to a learned classifier if false
# positives on real syllabi show this heuristic is too coarse.
_WEIGHT_KEYWORDS: list[tuple[str, float]] = [
    ("final", 0.35), ("midterm", 0.25), ("exam", 0.25),
    ("project", 0.15), ("essay", 0.15), ("paper", 0.15),
    ("assignment", 0.08), ("homework", 0.08), ("problem set", 0.08),
    ("quiz", 0.05), ("reading", 0.01),
]
_DEFAULT_WEIGHT = 0.05

# Any of these override the weight match above - "optional exam prep" isn't
# urgent just because it says "exam".
_LOW_STAKES_KEYWORDS = ("optional", "ungraded", "practice", "bonus", "not collected", "no submission", "0%")
_LOW_STAKES_WEIGHT = 0.01


def _infer_weight(description: str) -> float:
    text = description.lower()
    if any(keyword in text for keyword in _LOW_STAKES_KEYWORDS):
        return _LOW_STAKES_WEIGHT
    for keyword, weight in _WEIGHT_KEYWORDS:
        if keyword in text:
            return weight
    return _DEFAULT_WEIGHT


def classify_urgency(description: str, due: datetime | None, now: datetime | None = None) -> Urgency:
    """Urgency from free-text description + deadline, per docs/design.md's
    `weight / hours_until_due` sketch. No due date -> "low"."""
    if due is None:
        return "low"
    now = now or datetime.now(timezone.utc)
    if due < now:
        return "overdue"
    hours = max((due - now).total_seconds() / 3600, 1)
    score = _infer_weight(description) / hours
    if score >= 0.03:
        return "critical"
    if score >= 0.008:
        return "high"
    if score >= 0.001:
        return "medium"
    return "low"


@dataclass
class Textbook:
    course: str
    title: str
    isbn: str
    required: bool
    price: float | None
    url: str


# ISO weekday codes, Monday first - the same shorthand iCalendar's RRULE
# BYDAY uses, so a Meeting can be turned into a recurring VEVENT without a
# translation table.
Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@dataclass
class Meeting:
    """A recurring weekly class meeting (lecture, lab, seminar...) - distinct
    from Item, which is a single deadline. Comes from a school's own
    timetable/schedule export (hub/workday.py's Meeting Patterns column is
    the first source), not from a calendar feed or an LMS "due date".

    start_time/end_time are naive wall-clock times, not tz-aware datetimes:
    a Meeting recurs every week for the whole term, so there's no single
    instant to attach a timezone to - it's always interpreted in
    America/Vancouver, the same as every other display in this app."""
    course: str  # matches Course.code
    kind: str  # "lecture", "lab", "seminar", "tutorial", "exam"... - free-form, like Item.kind
    days: list[Weekday]
    start_time: time
    end_time: time
    location: str
    term_start: date
    term_end: date
    source: str
