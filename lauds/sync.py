"""Sync orchestration: run every adapter (or a chosen subset), save what
each one returns, and record what happened - never silently partial.

Iterates `lauds.adapters` by name; never imports a provider module by name
(BRIEF.md, "Adapters are plugins"). Each source gets its own try/except and
a hard wall-clock timeout (`_call_with_timeout`) so one stuck adapter can't
stall the others or the process: the call runs on a daemon thread and, on
timeout, `sync()` moves on and reports it as a failure while that thread is
abandoned (it never blocks process exit).

A lockfile (`paths.data_dir()/"sync.lock"`, `flock`) keeps two `sync()` runs
from overlapping and corrupting the same sqlite file.
"""
import queue
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lauds import adapters, paths, store
from lauds.session import NotLoggedIn

DEFAULT_TIMEOUT = 60  # seconds, per source

STALE_ERROR = "re-login needed"


class SyncLocked(Exception):
    """Another sync is already running (BRIEF.md: "a lockfile so two syncs
    can't overlap")."""


@dataclass
class SyncResult:
    source: str
    ok: bool
    counts: dict[str, int] | None = None
    error: str | None = None
    stale: bool = False  # NotLoggedIn: needs `lauds login <source>` again


@dataclass
class SyncReport:
    results: list[SyncResult] = field(default_factory=list)

    @property
    def any_failed(self) -> bool:
        return any(not r.ok for r in self.results)


def _call_with_timeout(fn, timeout: float):
    """Run `fn()` on a daemon thread; raise TimeoutError if it isn't done
    within `timeout` seconds. The thread is abandoned on timeout - daemon so
    it never keeps the process (or a test run) alive."""
    q: queue.Queue = queue.Queue(maxsize=1)

    def target():
        try:
            q.put(("ok", fn()))
        except BaseException as e:  # noqa: BLE001 - relayed to the caller below
            q.put(("err", e))

    t = threading.Thread(target=target, daemon=True)
    t.start()
    try:
        status, value = q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"timed out after {timeout}s") from None
    if status == "err":
        raise value
    return value


@contextmanager
def _lock(path: Path | None = None):
    """A non-blocking exclusive lock; raises SyncLocked immediately if held
    elsewhere, instead of waiting (BRIEF.md's "no hangups")."""
    path = Path(path) if path else (paths.ensure_dir(paths.data_dir()) / "sync.lock")
    fh = open(path, "a+")
    try:
        try:
            import fcntl

            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SyncLocked(f"another sync is already running (lock: {path})") from None
        except ImportError:
            pass  # no fcntl (non-POSIX): best effort, no lock
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        fh.close()


def _counts(bundle) -> dict[str, int]:
    return {k: len(getattr(bundle, k)) for k in ("courses", "items", "textbooks", "meetings")}


def sync_one(name: str, mod, conn, timeout: float, cfg: dict | None = None, **opts) -> SyncResult:
    """Fetch and save one source. Never raises - every failure becomes a
    `SyncResult(ok=False, ...)` so the caller's loop never needs its own
    try/except.

    `cfg` is this source's saved `lauds config set`/`lauds login --opt`
    values (`{}` if none); `adapters.fill_kwargs` matches them against
    `mod.fetch`'s own parameter names so a real per-adapter signature -
    `webwork.fetch(base, course_code)`, `bookstore.fetch(program, term)`,
    ... - actually gets driven instead of always being called as a bare
    `fetch()` (BRIEF blocker finding). A required kwarg with nothing
    configured for it is reported as a clear "needs config: ..." failure,
    not a bare `TypeError`. Anything in `opts` overrides `cfg` (a caller -
    e.g. a future scripted use of `sync_one` - can still pass exact kwargs
    through directly)."""
    kwargs, missing = adapters.fill_kwargs(mod.fetch, cfg or {})
    kwargs.update(opts)
    missing = [m for m in missing if m not in opts]
    if missing:
        err = ("needs config: " + ", ".join(f"{name}.{m}" for m in missing)
               + f" (run `lauds config set {name}.{missing[0]} <value>`)")
        store.record_sync(conn, name, False, error=err)
        return SyncResult(name, False, error=err)
    try:
        bundle = _call_with_timeout(lambda: mod.fetch(**kwargs), timeout)
    except NotLoggedIn:
        store.record_sync(conn, name, False, error=STALE_ERROR)
        return SyncResult(name, False, error=STALE_ERROR, stale=True)
    except TimeoutError as e:
        store.record_sync(conn, name, False, error=str(e))
        return SyncResult(name, False, error=str(e))
    except Exception as e:  # noqa: BLE001 - isolate one broken adapter from the rest
        store.record_sync(conn, name, False, error=f"{type(e).__name__}: {e}")
        return SyncResult(name, False, error=f"{type(e).__name__}: {e}")
    counts = _counts(bundle)
    store.save_bundle(conn, bundle)
    store.record_sync(conn, name, True, counts=counts)
    return SyncResult(name, True, counts=counts)


def sync(names: list[str] | None = None, timeout: float = DEFAULT_TIMEOUT, conn=None,
         adapters_map: dict[str, Any] | None = None, lock_path: Path | None = None) -> SyncReport:
    """Sync `names` (default: every discovered adapter, sorted), each in its
    own try/except with its own `timeout`. Returns a SyncReport whose
    `.any_failed` tells the CLI whether to exit non-zero; sources that
    succeeded are saved regardless of ones that failed."""
    own_conn = conn is None
    conn = conn or store.connect()
    reg = adapters.all_adapters() if adapters_map is None else dict(adapters_map)
    targets = list(names) if names else sorted(reg)
    report = SyncReport()
    try:
        with _lock(lock_path):
            for name in targets:
                if name not in reg:
                    err = adapters.load_errors.get(name)
                    msg = f"unknown adapter {name!r}" + (f" (failed to load: {err})" if err else "")
                    store.record_sync(conn, name, False, error=msg)
                    report.results.append(SyncResult(name, False, error=msg))
                    continue
                report.results.append(sync_one(name, reg[name], conn, timeout, cfg=paths.adapter_config(name)))
    finally:
        if own_conn:
            conn.close()
    return report


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
