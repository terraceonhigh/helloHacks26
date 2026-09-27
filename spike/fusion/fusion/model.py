"""The fusion model. Adapters emit observations; fuse.py turns them into tracks.

An observation is one sensor reading: what ONE source says about ONE thing,
as that source says it (raw course label, its own title, its own due). No
cross-source knowledge lives here. That is fuse.py's job.
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CourseObservation:
    source: str              # "moodle", "webwork", "prairielearn", "canvas", ...
    source_id: str           # the source's own stable id for the course
    label: str               # short code as the source prints it: "CPSC121-101-2026W1", "math100_2026w1"
    title: str               # long name as the source prints it
    term_hint: str | None    # term text if the source gives one, raw ("2026 Winter Term 1")
    url: str                 # the course's page on that source


@dataclass(frozen=True)
class Observation:
    source: str
    source_id: str           # stable within source; identity is (source, source_id)
    course_source_id: str    # the CourseObservation.source_id this belongs to (same source)
    kind: str                # assignment | quiz | exam | homework | lab | event | reading | announcement | ...
    title: str               # as the source prints it
    due: datetime | None     # tz-aware, the server's own instant. None = the source gives no due date
    opens: datetime | None   # tz-aware; set if not open yet / has an availability start
    url: str                 # deep link to this item's own page
    submit_url: str | None = None          # where the student submits, if different from url and knowable
    links_out: tuple[str, ...] = ()        # URLs in the item's body pointing at other hosts/platforms
    done: bool | None = None               # submitted/completed, if the source can tell. None = unknown
    weight: float | None = None            # fraction of final grade, if the source states it
    excerpt: str | None = None             # short raw text for provenance (<= 280 chars)


@dataclass(frozen=True)
class Snapshot:
    """Everything one adapter returned from one fetch."""
    source: str
    base: str
    fetched_at: datetime
    courses: tuple[CourseObservation, ...]
    items: tuple[Observation, ...]
    notes: tuple[str, ...] = ()            # non-fatal oddities worth surfacing in /health


@dataclass(frozen=True)
class CourseKey:
    subject: str             # "CPSC"
    number: str              # "121"
    term: str                # "2026W1"

    def __str__(self):
        return f"{self.subject} {self.number} / {self.term}"


@dataclass
class Provenance:
    value: object
    source: str
    source_id: str


@dataclass
class Conflict:
    field: str               # "due", "title", ...
    source: str
    source_id: str
    value: object            # what this source says instead
    chosen: object           # what the track uses


@dataclass
class Track:
    """One real-world piece of work, fused from every source that mentions it."""
    id: str
    course: CourseKey | str                   # str = unresolved course label (kept separate, warned)
    title: Provenance
    kind: Provenance
    due: Provenance | None
    opens: Provenance | None
    done: Provenance | None
    weight: Provenance | None
    action_url: str
    links: dict[str, str]                     # source -> that source's url
    members: list[Observation]
    evidence: list[dict] = field(default_factory=list)   # [{"a": (src,id), "b": (src,id), "kind": "link"|"title+due"|..., "due_delta_min": int|None}]
    conflicts: list[Conflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
