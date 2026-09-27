"""Snapshot <-> JSON, so live fetches can be saved as fixtures and replayed."""
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fusion.model import CourseObservation, Observation, Snapshot


def _enc(o):
    if isinstance(o, datetime):
        if o.tzinfo is None:
            raise ValueError(f"naive datetime in snapshot: {o!r}")
        return o.isoformat()
    raise TypeError(type(o))


def dumps(snap: Snapshot) -> str:
    return json.dumps(asdict(snap), default=_enc, indent=2, sort_keys=True)


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def loads(text: str) -> Snapshot:
    d = json.loads(text)
    courses = tuple(CourseObservation(**c) for c in d["courses"])
    items = tuple(
        Observation(**{**i, "due": _dt(i["due"]), "opens": _dt(i["opens"]), "links_out": tuple(i["links_out"])})
        for i in d["items"]
    )
    return Snapshot(source=d["source"], base=d["base"], fetched_at=_dt(d["fetched_at"]),
                    courses=courses, items=items, notes=tuple(d.get("notes", ())))


def save(snap: Snapshot, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(snap))


def load(path: Path) -> Snapshot:
    return loads(Path(path).read_text())


def load_dir(directory: Path) -> list[Snapshot]:
    return [load(p) for p in sorted(Path(directory).glob("*.json"))]
