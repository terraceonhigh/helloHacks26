"""Network-free: fake adapters in a tmp LAUDS_HOME, real lauds.store underneath."""
import json
import os
import stat
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from lauds import adapters, cli


@pytest.fixture
def env(tmp_path, monkeypatch):
    """LAUDS_HOME under tmp_path, plus two fake adapters (`canvas`: three
    dated items, a textbook and a meeting; `flaky`: always NotLoggedIn)."""
    monkeypatch.setenv("LAUDS_HOME", str(tmp_path / "home"))
    pkg = tmp_path / "plug"
    pkg.mkdir()
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(hours=2)).isoformat()
    mid = (now + timedelta(days=10)).isoformat()
    far = (now + timedelta(days=30)).isoformat()
    (pkg / "canvas.py").write_text(f'''
from datetime import time, date
from lauds.models import Bundle, Course, Item, Textbook, Meeting

NAME = "canvas"

def fetch(**kw):
    return Bundle(
        courses=[Course(code="CPSC 121", section="", term="2026W1",
                         title="Models of Computation", grade=88.5)],
        items=[
            Item(course="CPSC 121", category="deadline", kind="quiz", title="Quiz 2",
                 due=datetime_fromiso("{soon}"), url="https://x/q/1", source="canvas"),
            Item(course="CPSC 121", category="task", kind="assignment", title="PS3",
                 due=datetime_fromiso("{mid}"), url="https://x/a/3", source="canvas"),
            Item(course="CPSC 121", category="task", kind="assignment", title="PS9 (far off)",
                 due=datetime_fromiso("{far}"), url="https://x/a/9", source="canvas"),
            Item(course="CPSC 121", category="task", kind="assignment", title="Undated reading",
                 due=None, url="https://x/a/undated", source="canvas"),
        ],
        textbooks=[Textbook(course="CPSC 121", title="Discrete Math", isbn="123",
                             required=True, price=80.0, url="https://x/b/1")],
        meetings=[Meeting(course="CPSC 121", kind="lecture", days=["MO", "WE", "FR"],
                           start_time=time(10, 0), end_time=time(11, 0), location="ICCS 101",
                           term_start=date(2020, 1, 1), term_end=date(2030, 1, 1), source="workday")],
    )

def datetime_fromiso(s):
    from datetime import datetime as _dt
    return _dt.fromisoformat(s)

def login(**kw):
    pass
''')
    (pkg / "flaky.py").write_text('''
from lauds.session import NotLoggedIn
NAME = "flaky"
def fetch(**kw):
    raise NotLoggedIn("flaky")
''')
    (pkg / "needsconfig.py").write_text('''
from lauds.models import Bundle, Course
NAME = "needsconfig"
def login(base, course_code):
    pass
def fetch(base, course_code):
    return Bundle(courses=[Course(code="X", section="", term="", title=f"{base}/{course_code}")])
''')
    monkeypatch.setattr(adapters, "__path__", [str(pkg)])
    monkeypatch.setattr(adapters, "__name__", "clitest_plug")
    mod = types.ModuleType("clitest_plug")
    mod.__path__ = [str(pkg)]
    monkeypatch.setitem(sys.modules, "clitest_plug", mod)
    adapters.reset()
    yield tmp_path
    adapters.reset()


def _run(argv, capsys):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


# --- login -------------------------------------------------------------------

def test_login_calls_the_adapters_login(env, capsys):
    code, out, _ = _run(["login", "canvas"], capsys)
    assert code == 0 and "session saved" in out


def test_login_no_login_step(env, capsys):
    code, out, _ = _run(["login", "flaky"], capsys)  # flaky has fetch() but no login()
    assert code == 0 and "no login step needed" in out


def test_login_unknown_source(env, capsys):
    code, _, err = _run(["login", "nope"], capsys)
    assert code == 1 and "unknown adapter" in err


def test_login_reports_missing_required_config_instead_of_a_typeerror(env, capsys):
    code, _, err = _run(["login", "needsconfig"], capsys)
    assert code == 1
    assert "base" in err and "course_code" in err


def test_login_with_opts_drives_login_and_saves_config_for_later(env, capsys):
    from lauds import paths
    code, out, _ = _run(["login", "needsconfig", "--opt", "base=https://ww.example.edu",
                          "--opt", "course_code=math100"], capsys)
    assert code == 0 and "session saved" in out
    assert paths.adapter_config("needsconfig") == {"base": "https://ww.example.edu", "course_code": "math100"}
    # a later sync needs no --opt at all: the saved config drives fetch()
    code, out, _ = _run(["sync", "needsconfig"], capsys)
    assert code == 0 and "needsconfig: ok" in out


def test_sync_reports_missing_config_as_a_clear_error(env, capsys):
    code, out, err = _run(["sync", "needsconfig"], capsys)
    assert code == 1
    assert "needsconfig: FAILED - needs config" in err and "base" in err


def test_config_set_dotted_key_drives_sync_without_login(env, capsys):
    _run(["config", "set", "needsconfig.base", "https://ww.example.edu"], capsys)
    _run(["config", "set", "needsconfig.course_code", "math100"], capsys)
    code, out, _ = _run(["sync", "needsconfig"], capsys)
    assert code == 0 and "needsconfig: ok" in out


# --- sync / status -------------------------------------------------------------

def test_sync_saves_good_sources_and_reports_the_bad_one(env, capsys):
    code, out, err = _run(["sync"], capsys)
    assert code == 1  # flaky failed
    assert "canvas: ok" in out
    assert "flaky: re-login needed" in err


def test_sync_one_named_source(env, capsys):
    code, out, _ = _run(["sync", "canvas"], capsys)
    assert code == 0 and "canvas: ok" in out


def test_status_after_sync_shows_stale_flag(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["status", "--json"], capsys)
    rows = {r["source"]: r for r in json.loads(out)}
    assert rows["canvas"]["ok"] is True and not rows["canvas"]["stale"]
    assert rows["flaky"]["ok"] is False and rows["flaky"]["stale"]


def test_status_before_any_sync_shows_never(env, capsys):
    code, out, _ = _run(["status", "--json"], capsys)
    rows = {r["source"]: r for r in json.loads(out)}
    assert rows["canvas"]["ok"] is None


# --- query commands ------------------------------------------------------------

def test_today_json_is_a_list(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["today", "--json"], capsys)
    assert code == 0
    assert isinstance(json.loads(out), list)


def test_due_default_window_excludes_far_future(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["due", "--json"], capsys)
    titles = {r["title"] for r in json.loads(out)}
    assert {"Quiz 2", "PS3"} <= titles and "PS9 (far off)" not in titles


def test_due_week_only_the_soon_item(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["due", "--week", "--json"], capsys)
    titles = {r["title"] for r in json.loads(out)}
    assert titles == {"Quiz 2"}


def test_due_days_wide_window_includes_everything(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["due", "--days", "40", "--json"], capsys)
    titles = {r["title"] for r in json.loads(out)}
    assert titles == {"Quiz 2", "PS3", "PS9 (far off)"}


def test_due_filters_by_course(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["due", "--days", "40", "--course", "cpsc121", "--json"], capsys)  # canonicalises
    assert all(r["course"] == "CPSC 121" for r in json.loads(out))
    assert len(json.loads(out)) == 3


def test_due_item_json_schema(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["due", "--json"], capsys)
    row = json.loads(out)[0]
    assert set(row) == {"id", "course", "category", "kind", "title", "due", "url", "source", "done", "status"}
    assert isinstance(row["id"], int) and row["status"] in ("done", "overdue", "soon", "upcoming")


def test_course_command(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["course", "CPSC 121", "--json"], capsys)
    d = json.loads(out)
    assert d["course"]["code"] == "CPSC 121" and d["course"]["grade"] == 88.5
    # BRIEF major finding: `course` used to only ever show by_course()'s
    # dated items - an undated one (a WeBWorK not-open set, Canvas's own
    # to_undated_item, ...) must show here too, not just via `show <id>`.
    assert len(d["items"]) == 4
    assert "Undated reading" in {i["title"] for i in d["items"]}
    assert len(d["textbooks"]) == 1 and d["textbooks"][0]["isbn"] == "123"
    assert len(d["schedule"]) == 1 and d["schedule"][0]["days"] == ["MO", "WE", "FR"]


def test_undated_command(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["undated", "--json"], capsys)
    assert code == 0
    titles = {r["title"] for r in json.loads(out)}
    assert titles == {"Undated reading"}
    assert all(r["due"] is None for r in json.loads(out))


def test_undated_filters_by_course(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["undated", "--course", "cpsc121", "--json"], capsys)  # canonicalises
    assert {r["title"] for r in json.loads(out)} == {"Undated reading"}
    code, out, _ = _run(["undated", "--course", "math100", "--json"], capsys)
    assert json.loads(out) == []


def test_show_full_item_and_unknown_id(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["due", "--json"], capsys)
    item_id = next(r["id"] for r in json.loads(out) if r["title"] == "Quiz 2")
    code, out, _ = _run(["show", str(item_id), "--json"], capsys)
    d = json.loads(out)
    assert code == 0 and d["title"] == "Quiz 2" and d["url"] == "https://x/q/1" and d["files"] == []

    code, _, err = _run(["show", "999999"], capsys)
    assert code == 1 and "no item" in err


def test_schedule_filtered_by_date(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["schedule", "--date", "2026-09-28", "--json"], capsys)  # a Monday, "MO" in days
    assert len(json.loads(out)) == 1
    _, out, _ = _run(["schedule", "--date", "2026-09-29", "--json"], capsys)  # a Tuesday
    assert json.loads(out) == []


def test_textbooks_command(env, capsys):
    _run(["sync"], capsys)
    _, out, _ = _run(["textbooks", "--json"], capsys)
    rows = json.loads(out)
    assert rows[0]["isbn"] == "123" and rows[0]["required"] is True


# --- sql ------------------------------------------------------------------

def test_sql_select_ok(env, capsys):
    _run(["sync"], capsys)
    code, out, _ = _run(["sql", "SELECT count(*) AS n FROM items", "--json"], capsys)
    assert code == 0 and json.loads(out) == [{"n": 4}]


def test_sql_rejects_writes(env, capsys):
    _run(["sync"], capsys)
    code, _, err = _run(["sql", "DELETE FROM items"], capsys)
    assert code == 1 and "SELECT/WITH" in err


def test_sql_rejects_second_statement(env, capsys):
    _run(["sync"], capsys)
    code, _, err = _run(["sql", "SELECT 1; DELETE FROM items"], capsys)
    assert code == 1 and "single statement" in err


def test_sql_is_actually_readonly_at_the_db_level(env, capsys):
    # Even a query that *looks* like a SELECT can't write: the connection
    # itself is opened uri mode=ro (belt and suspenders over the regex).
    _run(["sync"], capsys)
    from lauds import store
    conn = store.connect_readonly()
    with pytest.raises(Exception):
        conn.execute("DELETE FROM items")


# --- export ics -------------------------------------------------------------

def test_export_ics_writes_a_file(env, capsys, tmp_path):
    _run(["sync"], capsys)
    out_file = tmp_path / "feed.ics"
    code, out, _ = _run(["export", "ics", "--out", str(out_file)], capsys)
    assert code == 0 and out_file.exists()
    text = out_file.read_text()
    assert "BEGIN:VCALENDAR" in text and "Quiz 2 [CPSC 121]" in text


# --- config ------------------------------------------------------------------

def test_config_set_is_stored_and_not_echoed_in_full(env, capsys):
    code, out, _ = _run(["config", "set", "canvas-feed-url", "https://example.com/verysecretfeedtoken"], capsys)
    assert code == 0
    assert "verysecretfeedtoken" not in out
    from lauds import paths
    path = paths.config_dir() / "config.json"
    data = json.loads(path.read_text())
    assert data["canvas-feed-url"] == "https://example.com/verysecretfeedtoken"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
