"""HTTP server on an ephemeral localhost port against the scenario snapshots."""
import json
import sys
import types
import urllib.error
import urllib.request

import pytest

from fusion import run, serve
from fusion.snapshot_io import save
from tests import scenario as S


@pytest.fixture(scope="module")
def snapdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("snaps")
    for s in S.snapshots():
        save(s, d / f"{s.source}.json")
    (d / "brokensource.json").write_text("{not json")
    return d


@pytest.fixture(scope="module")
def base(snapdir):
    state = serve.build_state(run.collect({"snapshots": str(snapdir)}))
    srv, _ = serve.serve_in_thread(state, 0, now=lambda: S.NOW)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=5) as r:
            assert r.headers["Content-Type"].startswith("application/json")
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        assert e.headers["Content-Type"].startswith("application/json")
        return e.code, json.loads(e.read())


def test_bound_to_loopback(base):
    assert base.startswith("http://127.0.0.1:")


def test_tracks_default(base):
    code, body = get(base, "/tracks")
    assert code == 200 and body["count"] == 14 and len(body["tracks"]) == 14
    first, last = body["tracks"][0], body["tracks"][-1]
    assert (first["title"], first["status"]) == ("HW1", "overdue")
    assert (last["title"], last["status"]) == ("Reading: Chapter 4", "undated")
    assert body["now"].startswith("2026-09-27T12:00:00-07:00")
    hw2 = next(t for t in body["tracks"] if t["title"] == "HW2")
    assert hw2["action_url"] == S.ww("HW2") and hw2["conflicts"] == 1
    assert hw2["links"] == {"moodle": S.md(2), "webwork": S.ww("HW2")}


def test_tracks_all_and_done(snapdir, tmp_path):
    from dataclasses import replace
    snaps = [replace(s, items=tuple(replace(o, done=True) if o == S.OBS["W1"] else o for o in s.items))
             for s in S.snapshots()]
    results = [run.SourceResult(s.source, s, fetched_at=s.fetched_at) for s in snaps]
    srv, _ = serve.serve_in_thread(serve.build_state(results), 0, now=lambda: S.NOW)
    b = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert get(b, "/tracks")[1]["count"] == 13
        body = get(b, "/tracks?all=1")[1]
        assert body["count"] == 14 and any(t["status"] == "done" for t in body["tracks"])
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("q,n", [("CPSC%20121", 6), ("MATH100", 6), ("ENGL%20110%20%2F%202026W1", 2),
                                 ("CPSC%20999", 0)])
def test_tracks_course_filter(base, q, n):
    code, body = get(base, f"/tracks?course={q}")
    assert code == 200 and body["count"] == n


def test_track_detail_and_404(base):
    _, body = get(base, "/tracks?course=CPSC%20121")
    q1 = next(t for t in body["tracks"] if t["title"] == "Quiz 1")
    code, d = get(base, f"/tracks/{q1['id']}")
    assert code == 200
    assert {(m["source"], m["source_id"]) for m in d["members"]} == {
        ("prairielearn", "1:quiz1"), ("moodle", "cm:9"), ("canvas", "assignment:51001")}
    assert {e["kind"] for e in d["evidence"]} == {"link", "title+undated"}
    assert d["provenance"]["due"] == {"value": "2026-10-02T23:59:00-07:00", "source": "prairielearn",
                                      "source_id": "1:quiz1"}
    assert d["course_labels"]
    code, d = get(base, "/tracks/deadbeef0000")
    assert code == 404 and "error" in d
    assert get(base, "/nope")[0] == 404


def test_track_detail_conflicts(base):
    _, body = get(base, "/tracks")
    hw2 = next(t for t in body["tracks"] if t["title"] == "HW2")
    d = get(base, f"/tracks/{hw2['id']}")[1]
    assert d["conflicts"] == [{"field": "due", "source": "moodle", "source_id": "cm:2",
                               "value": "2026-09-29T23:00:00-07:00", "chosen": "2026-09-29T23:59:00-07:00",
                               "delta_min": -59}]


def test_courses(base):
    code, body = get(base, "/courses")
    assert code == 200
    keys = [c["key"] for c in body["courses"]]
    assert keys == ["CPSC 121 / 2026W1", "ENGL 110 / 2026W1", "MATH 100 / 2026W1"]
    cpsc = body["courses"][0]
    assert {l["source"] for l in cpsc["labels"]} == {"moodle", "prairielearn", "canvas"}


def test_observations(base):
    code, body = get(base, "/observations")
    assert code == 200 and body["count"] == 19
    m5 = next(o for o in body["observations"] if o["source_id"] == "cm:9")
    assert m5["due"] is None and m5["course"] == "CPSC 121 / 2026W1" and m5["links_out"] == [S.pl(1)]


def test_health_shows_failing_source_others_serve(base):
    code, body = get(base, "/health")
    assert code == 200 and body["ok"] is False
    by = {s["source"]: s for s in body["sources"]}
    assert by["brokensource"]["ok"] is False and "JSONDecodeError" in by["brokensource"]["error"]
    for name, n in (("webwork", 4), ("prairielearn", 4), ("moodle", 9), ("canvas", 2)):
        assert by[name]["ok"] is True and by[name]["observations"] == n and by[name]["fetched_at"]
    assert get(base, "/tracks")[1]["count"] == 14


def test_live_collect_isolates_failures(tmp_path, monkeypatch):
    """--live path: a login or adapter that raises becomes a health entry, never an exception."""
    snaps = {s.source: s for s in S.snapshots()}
    good_adapter = types.ModuleType("fx_good_adapter")
    good_adapter.fetch = lambda session, base: snaps["moodle"]
    bad_adapter = types.ModuleType("fx_bad_adapter")

    def boom(session, base):
        raise ConnectionError("server down")
    bad_adapter.fetch = boom
    login = types.ModuleType("fx_login")
    seen = {}

    def do_login(base, secrets):
        seen[base] = secrets
        return object()
    login.login = do_login
    for m in (good_adapter, bad_adapter, login):
        monkeypatch.setitem(sys.modules, m.__name__, m)
    (tmp_path / "s.env").write_text("# c\nFSTUDENT_PASSWORD='x y'\nexport FOO=bar\n")
    toml = tmp_path / "sources.toml"
    toml.write_text(f'''
[[source]]
name = "moodle"
base = "http://localhost:8082"
adapter = "fx_good_adapter"
login = "fx_login"
secrets = "{tmp_path / 's.env'}"

[[source]]
name = "webwork"
base = "http://localhost:8081"
adapter = "fx_bad_adapter"
login = "fx_login"
secrets = "{tmp_path / 's.env'}"

[[source]]
name = "nosecrets"
base = "http://localhost:1"
adapter = "fx_good_adapter"
login = "fx_login"
secrets = "does/not/exist.env"
''')
    results = run.collect({"live": str(toml)})
    h = {x["source"]: x for x in run.health(results)}
    assert h["moodle"]["ok"] and h["moodle"]["observations"] == 9
    assert not h["webwork"]["ok"] and "server down" in h["webwork"]["error"]
    assert not h["nosecrets"]["ok"] and "FileNotFoundError" in h["nosecrets"]["error"]
    assert seen["http://localhost:8082"] == {"FSTUDENT_PASSWORD": "x y", "FOO": "bar"}
    state = serve.build_state(results)
    assert len(state.tracks) == 9 and state.fuse_error is None


def test_naive_snapshot_fails_only_that_source(tmp_path):
    for s in S.snapshots():
        save(s, tmp_path / f"{s.source}.json")
    d = json.loads((tmp_path / "webwork.json").read_text())
    for i in d["items"]:
        if i["due"]:
            i["due"] = i["due"][:19]            # strip the offset: naive
    (tmp_path / "webwork.json").write_text(json.dumps(d))
    results = run.collect({"snapshots": str(tmp_path)})
    h = {x["source"]: x for x in run.health(results)}
    assert not h["webwork"]["ok"] and "naive" in h["webwork"]["error"]
    state = serve.build_state(results)
    # without WeBWorK: HW1/HW2 survive as Moodle-only tracks, HW9/HW3 vanish -> 14 - 2
    assert state.fuse_error is None and len(state.tracks) == 12


def test_live_source_that_never_answers_fails_alone(tmp_path, monkeypatch):
    import threading
    snaps = {s.source: s for s in S.snapshots()}
    release = threading.Event()
    hang = types.ModuleType("fx_hang_adapter")
    hang.fetch = lambda session, base: (release.wait(30), snaps["webwork"])[1]
    good = types.ModuleType("fx_good_adapter2")
    good.fetch = lambda session, base: snaps["moodle"]
    login = types.ModuleType("fx_login2")
    login.login = lambda base, secrets: object()
    for m in (hang, good, login):
        monkeypatch.setitem(sys.modules, m.__name__, m)
    (tmp_path / "s.env").write_text("X=1\n")
    src = {"login": "fx_login2", "secrets": str(tmp_path / "s.env"), "deadline_s": 0.5}
    try:
        results = run.collect({"sources": [{**src, "name": "webwork", "adapter": "fx_hang_adapter"},
                                           {**src, "name": "moodle", "adapter": "fx_good_adapter2"}]})
    finally:
        release.set()
    h = {x["source"]: x for x in run.health(results)}
    assert not h["webwork"]["ok"] and "TimeoutError" in h["webwork"]["error"]
    assert h["moodle"]["ok"] and h["moodle"]["observations"] == 9
