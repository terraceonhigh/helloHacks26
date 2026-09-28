"""Network-free: fake adapters only, in a tmp LAUDS_HOME."""
import time
import types

import pytest

from lauds import store, sync
from lauds.models import Bundle, Course, Item
from lauds.session import NotLoggedIn


def _mod(name, fetch=None, login=None):
    m = types.SimpleNamespace(NAME=name, fetch=fetch or (lambda **kw: Bundle()))
    if login is not None:
        m.login = login
    return m


BUNDLE = Bundle(courses=[Course(code="CPSC 121", section="", term="2026W1", title="Models of Computation")],
                items=[Item(course="CPSC 121", category="task", kind="assignment", title="PS1",
                            due=None, url="https://x/1", source="good")])


@pytest.fixture
def conn():
    return store.connect(":memory:")


def test_sync_one_saves_and_records_success(conn):
    result = sync.sync_one("good", _mod("good", fetch=lambda **kw: BUNDLE), conn, timeout=5)
    assert result.ok and result.counts == {"courses": 1, "items": 1, "textbooks": 0, "meetings": 0}
    assert store.upcoming(conn) == []  # the item is undated
    assert store.undated(conn)[0][3] == "PS1"
    [(source, attempt, success, ok, counts, err)] = store.sync_status(conn)
    assert (source, ok, err) == ("good", True, None)
    assert counts == {"courses": 1, "items": 1, "textbooks": 0, "meetings": 0}


def test_not_logged_in_marks_stale_never_partial(conn):
    def fetch(**kw):
        raise NotLoggedIn("canvas")

    result = sync.sync_one("canvas", _mod("canvas", fetch=fetch), conn, timeout=5)
    assert not result.ok and result.stale and result.error == sync.STALE_ERROR
    [(_, _, _, ok, counts, err)] = store.sync_status(conn)
    assert not ok and err == sync.STALE_ERROR and counts is None


def test_broken_adapter_is_isolated(conn):
    def fetch(**kw):
        raise RuntimeError("boom")

    result = sync.sync_one("broken", _mod("broken", fetch=fetch), conn, timeout=5)
    assert not result.ok and not result.stale and "boom" in result.error


def test_hanging_adapter_times_out_and_does_not_block(conn):
    def fetch(**kw):
        time.sleep(30)  # far longer than the timeout below; thread is abandoned (daemon)
        return Bundle()

    started = time.monotonic()
    result = sync.sync_one("slow", _mod("slow", fetch=fetch), conn, timeout=0.2)
    elapsed = time.monotonic() - started
    assert not result.ok and "timed out" in result.error
    assert elapsed < 5  # proves sync_one returned promptly, not after the full sleep


def test_one_source_failing_does_not_stop_the_others(conn):
    good_bundle = Bundle(items=[Item(course="X", category="task", kind="assignment", title="A",
                                      due=None, url="https://x/good", source="good")])
    reg = {
        "good": _mod("good", fetch=lambda **kw: good_bundle),
        "bad": _mod("bad", fetch=lambda **kw: (_ for _ in ()).throw(RuntimeError("nope"))),
    }
    report = sync.sync(conn=conn, adapters_map=reg, timeout=5)
    assert report.any_failed
    by_source = {r.source: r for r in report.results}
    assert by_source["good"].ok and not by_source["bad"].ok
    # good's data was saved despite bad's failure (raw query: no Course "X"
    # was saved this call, so store.undated()'s course JOIN would hide it).
    assert [r[0] for r in conn.execute("SELECT title FROM items").fetchall()] == ["A"]


def test_sync_defaults_to_every_registered_adapter(conn):
    reg = {"a": _mod("a"), "b": _mod("b")}
    report = sync.sync(conn=conn, adapters_map=reg, timeout=5)
    assert sorted(r.source for r in report.results) == ["a", "b"]


def test_unknown_source_name_is_a_per_source_failure_not_a_crash(conn):
    report = sync.sync(["nope"], conn=conn, adapters_map={"good": _mod("good")}, timeout=5)
    assert report.any_failed and report.results[0].source == "nope" and not report.results[0].ok


def test_exit_code_nonzero_iff_any_failed(conn):
    ok_reg = {"good": _mod("good")}
    assert not sync.sync(conn=store.connect(":memory:"), adapters_map=ok_reg, timeout=5).any_failed
    bad_reg = {"bad": _mod("bad", fetch=lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))}
    assert sync.sync(conn=store.connect(":memory:"), adapters_map=bad_reg, timeout=5).any_failed


def test_two_syncs_cannot_overlap(tmp_path):
    lock_path = tmp_path / "sync.lock"
    slow_started = []

    def slow_fetch(**kw):
        slow_started.append(True)
        time.sleep(0.3)
        return Bundle()

    import threading

    results = {}

    def run_a():
        # sqlite connections are thread-local: create this thread's conn here.
        conn_a = store.connect(":memory:")
        results["a"] = sync.sync(conn=conn_a, adapters_map={"slow": _mod("slow", fetch=slow_fetch)},
                                  timeout=5, lock_path=lock_path)

    t = threading.Thread(target=run_a, daemon=True)
    t.start()
    time.sleep(0.05)  # let the first sync grab the lock
    with pytest.raises(sync.SyncLocked):
        sync.sync(conn=store.connect(":memory:"), adapters_map={"slow": _mod("slow", fetch=slow_fetch)},
                  timeout=5, lock_path=lock_path)
    t.join(timeout=5)
    assert not t.is_alive()
    assert results["a"].results[0].ok
