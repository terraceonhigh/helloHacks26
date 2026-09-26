"""The shared model (docs/design.md §4). Every adapter returns these; the UI only reads these."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Course:
    key: str  # "UBCV,2026W1,CPSC,CPSC121,101", the join key
    code: str  # "CPSC 121"
    section: str  # "101"
    term: str  # "2026W1"
    title: str
    grade: float | None = None
    instructor: str | None = None
    schedule: list[dict] = field(default_factory=list)  # [{"day", "start", "end", "room"}]
    sources: list[str] = field(default_factory=list)


@dataclass
class Item:
    id: str  # "source:type:upstream_id"
    course_key: str | None
    kind: str  # assignment | quiz | exam | event | announcement
    title: str
    due: datetime | None  # timezone-aware
    url: str | None
    source: str  # canvas | ics | workday | bookstore
    done: bool = False


@dataclass
class Textbook:
    course_key: str
    title: str
    isbn: str
    required: bool
    price_new: float | None = None
    price_used: float | None = None
    price_digital: float | None = None
    store_url: str | None = None
