"""The shared model every adapter returns.

A strict superset of main's hub/models.py: every field main has keeps its
name, position, type and default, so `compat.to_main` is a projection, never a
translation. New fields are appended after main's, always with a default.

Not ported on purpose: main's urgency keyword classifier (classify_urgency /
_infer_weight) - see BRIEF.md "Thrown out".
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

Category = Literal["task", "deadline", "material"]

# What bucket a given kind falls into. Adapters pick a specific `kind`
# ("assignment", "quiz", "reading", ...); this decides which of the three
# lists (tasks / deadlines-and-key-dates / materials) it lands in.
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
    grade: float | None = None  # current score %, if the source knows it
    # --- lauds additions (not in main; compat.to_main drops them) ---
    source: str = ""  # which adapter reported this course, "" = unknown
    url: str | None = None


@dataclass
class ItemFile:
    """One thing attached to an Item - a reading, a template, a folder.
    `kind` picks the icon; `folder` has no direct download."""
    name: str
    url: str
    kind: Literal["file", "folder", "link"] = "file"


@dataclass
class Item:
    course: str
    category: Category
    kind: str  # free-form label within the category, e.g. "quiz", "reading"
    title: str
    due: datetime | None  # tz-aware or None - enforced in __post_init__
    url: str
    source: str
    done: bool | None = None  # completed/submitted, if the source can tell. None = unknown
    # [] (the default) means "not fetched", not "genuinely no files".
    files: list[ItemFile] = field(default_factory=list)
    # --- lauds additions (not in main; compat.to_main drops them) ---
    description: str | None = None  # plain text or HTML as the source gave it
    points: float | None = None  # points possible, if the source says
    extra: dict[str, Any] = field(default_factory=dict)  # adapter-specific leftovers (JSON-safe)

    def __post_init__(self):
        if self.due is not None and (self.due.tzinfo is None or self.due.utcoffset() is None):
            raise ValueError(f"Item.due must be tz-aware or None, got naive {self.due!r} ({self.source} {self.url})")

    @property
    def key(self) -> tuple[str, str]:
        """Identity across syncs and adapters: (source, url)."""
        return (self.source, self.url)


Status = Literal["done", "overdue", "soon", "upcoming"]
SOON_WINDOW = timedelta(hours=48)  # "due within 48h" is "soon", inclusive


def status_of(item: Item, now: datetime | None = None) -> Status:
    """Where an item sits right now. Never stored - a pure function of
    `done`, `due` and `now`, recomputed on every read, so it's never stale."""
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


# ISO weekday codes, Monday first - iCalendar RRULE BYDAY's shorthand.
Weekday = Literal["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


@dataclass
class Meeting:
    """A recurring weekly class meeting (lecture, lab, seminar...), distinct
    from Item (a single deadline). start_time/end_time are naive wall-clock
    times, always interpreted in America/Vancouver: a meeting recurs all term,
    so there's no single instant to attach a timezone to."""
    course: str  # matches Course.code
    kind: str  # "lecture", "lab", "seminar", ... free-form
    days: list[Weekday]
    start_time: time
    end_time: time
    location: str
    term_start: date
    term_end: date
    source: str


@dataclass
class Bundle:
    """What an adapter's fetch() returns: everything one sync produced."""
    courses: list[Course] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    textbooks: list[Textbook] = field(default_factory=list)
    meetings: list[Meeting] = field(default_factory=list)

    def extend(self, other: "Bundle") -> "Bundle":
        for name in ("courses", "items", "textbooks", "meetings"):
            getattr(self, name).extend(getattr(other, name))
        return self


# --- course codes (main's hub/logic.normalise_course_code) -----------------

_COURSE_CODE_RE = re.compile(
    r"^(?P<faculty>[a-z]{2,5})[ _-]?[a-z]*[ _-]*"
    r"(?P<number>\d{2,4})[ _-]*(?P<section>\d{2,4})?",
    re.IGNORECASE,
)


def normalise_course_code(text: str):
    """"CPSC 121 101 2026W1" -> ("CPSC", "121", "101"); unparseable -> (None, None, None)."""
    match = _COURSE_CODE_RE.match(text.strip())
    if not match:
        return None, None, None
    return match.group("faculty").upper(), match.group("number"), match.group("section")


def canonical_code(code: str) -> str:
    """Collapse every spelling of a course to "FACULTY NUMBER" (section
    dropped); falls back to the raw text when it doesn't parse."""
    faculty, number, _section = normalise_course_code(code)
    return f"{faculty} {number}" if faculty and number else code


def canonical_term(term: str | None) -> str:
    """"2026 Winter Term 1" -> "2026W1"; "" / None -> "" (= unknown)."""
    # ponytail: only UBC's "<year> Winter|Summer Term <n>" spelling is mapped;
    # anything else is kept as-is. Add a pattern when a new source needs one.
    term = (term or "").strip()
    m = re.fullmatch(r"(\d{4})\s+(Winter|Summer)\s+Term\s+(\d)", term, re.I)
    return f"{m[1]}{m[2][0].upper()}{m[3]}" if m else term
