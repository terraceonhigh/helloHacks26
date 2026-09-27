"""Collect snapshots (saved JSON or live from configured servers), per source, never raising.

    collect(config) -> list[SourceResult]
    snapshots(results) -> list[Snapshot]
    health(results) -> list[dict]

config is one of:
    {"snapshots": "<dir>"}                       every *.json in dir is one source's Snapshot
    {"live": "oracles/sources.toml"}             [[source]] name, base, adapter, login, secrets
                                                 plus optional [[snapshot]] path = "<file.json>" entries,
                                                 replayed alongside the live sources (a provider with no
                                                 live server, e.g. the synthetic Canvas fixture)
    {"sources": [{name, base, adapter, login, secrets}, ...]}   same, already parsed
"""
from __future__ import annotations

import importlib
import sys
import threading
import tomllib
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fusion import snapshot_io
from fusion.model import Snapshot

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class SourceResult:
    name: str
    snapshot: Snapshot | None = None
    error: str | None = None
    fetched_at: datetime | None = None
    origin: str = ""                      # file path or base URL
    notes: list[str] = field(default_factory=list)


def parse_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments ignored; optional surrounding quotes stripped."""
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k.strip().removeprefix("export ").strip()] = v
    return out


def load_sources_toml(path: str | Path) -> list[dict]:
    with open(path, "rb") as f:
        return list(tomllib.load(f).get("source", []))


def load_snapshot_entries(path: str | Path) -> list[dict]:
    """[[snapshot]] entries of a sources.toml: {path = "fixtures/snapshots/canvas.json"}."""
    with open(path, "rb") as f:
        return list(tomllib.load(f).get("snapshot", []))


def _resolve(p: str, anchor: Path) -> Path:
    for cand in (Path(p), anchor / p, ROOT / p):
        if cand.exists():
            return cand
    return Path(p)


def _err(e: BaseException) -> str:
    # never include locals/args (could hold secrets): type + message + innermost frame only
    tb = traceback.extract_tb(e.__traceback__)
    where = f" at {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
    return f"{type(e).__name__}: {e}{where}"


def validate(snap: Snapshot) -> Snapshot:
    """Reject a snapshot fusion can't use (naive datetimes), so it fails as ONE source."""
    for o in snap.items:
        for name in ("due", "opens"):
            v = getattr(o, name)
            if v is not None and v.utcoffset() is None:
                raise ValueError(f"naive datetime {name} in {o.source}:{o.source_id}")
    return snap


def collect_file(p: str | Path) -> SourceResult:
    """One saved Snapshot file as one source; a bad file is that source's error, never a crash."""
    p = Path(p)
    try:
        snap = validate(snapshot_io.load(p))
        return SourceResult(snap.source, snap, fetched_at=snap.fetched_at, origin=str(p),
                            notes=list(snap.notes))
    except Exception as e:  # noqa: BLE001 - a broken source must not break the others
        return SourceResult(p.stem, error=_err(e), origin=str(p))


def collect_dir(directory: str | Path) -> list[SourceResult]:
    # same file set/order as snapshot_io.load_dir, but one bad file is one error, not a crash
    return [collect_file(p) for p in sorted(Path(directory).glob("*.json"))]


DEADLINE_S = 180.0   # per source, login + fetch; override per [[source]] with deadline_s


def with_deadline(fn, seconds: float):
    """fn() in a worker thread; its result, its exception, or TimeoutError after `seconds`.

    A source whose server accepts the connection and never answers (or an adapter that
    forgot a request timeout) then fails as ONE source instead of hanging every other one.
    """
    # ponytail: a Python thread can't be killed, so a timed-out fetch keeps running as a
    # daemon thread until its socket gives up. Upgrade path: a subprocess per source.
    box: dict = {}

    def work():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - handed back to the caller
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"no answer within {seconds:g}s (login + fetch)")
    if "error" in box:
        raise box["error"]
    return box["value"]


def collect_live(sources: list[dict], anchor: Path = ROOT) -> list[SourceResult]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    results = []
    for src in sources:
        name = src.get("name", "?")
        base = src.get("base", "")
        started = datetime.now(timezone.utc)
        try:
            adapter = importlib.import_module(src.get("adapter") or f"fusion.adapters.{name}")
            login = importlib.import_module(src.get("login") or f"oracles.{name}.login")
            secrets_path = src.get("secrets") or f"oracles/{name}/secrets.env"
            secrets = parse_env(_resolve(secrets_path, anchor))
            snap = validate(with_deadline(lambda: adapter.fetch(login.login(base, secrets), base),
                                          float(src.get("deadline_s", DEADLINE_S))))
            results.append(SourceResult(name, snap, fetched_at=snap.fetched_at, origin=base,
                                        notes=list(snap.notes)))
        except Exception as e:  # noqa: BLE001 - per-source isolation (SPEC: fetch raises, run catches)
            results.append(SourceResult(name, error=_err(e), fetched_at=started, origin=base))
    return results


def collect(config: dict) -> list[SourceResult]:
    """One SourceResult per source. A failing source carries .error and no snapshot."""
    if "snapshots" in config:
        return collect_dir(config["snapshots"])
    if "live" in config:
        path = Path(config["live"])
        try:
            sources = load_sources_toml(path)
            replays = load_snapshot_entries(path)
        except Exception as e:  # noqa: BLE001
            return [SourceResult(str(path), error=_err(e), origin=str(path))]
        anchor = path.resolve().parent
        return (collect_live(sources, anchor=anchor)
                + [collect_file(_resolve(r["path"], anchor)) for r in replays])
    if "sources" in config:
        return collect_live(config["sources"])
    raise ValueError("config needs 'snapshots', 'live' or 'sources'")


def snapshots(results: list[SourceResult]) -> list[Snapshot]:
    return [r.snapshot for r in results if r.snapshot is not None]


def health(results: list[SourceResult]) -> list[dict]:
    out = []
    for r in results:
        s = r.snapshot
        out.append({
            "source": r.name, "ok": r.error is None, "error": r.error, "origin": r.origin,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            "courses": len(s.courses) if s else 0,
            "observations": len(s.items) if s else 0,
            "dated": sum(1 for i in s.items if i.due) if s else 0,
            "undated": sum(1 for i in s.items if not i.due) if s else 0,
            "notes": r.notes,
        })
    return out
