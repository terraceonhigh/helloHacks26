"""Parity oracle: does web/ show what the frozen app.py shows? (issue #31)

Opt-in, not part of `uv run pytest` (the file isn't named test_*.py). Builds
ONE fixture hub.db from fake Course/Item rows via hub.db.save, then:

  * app.py  - rendered in-process with streamlit.testing.v1.AppTest, Sample
              data OFF, hub.db.connect() pointed at the fixture;
  * web/    - `python -m hub.api` (this checkout's API) on the same fixture
              plus `next dev` with NEXT_PUBLIC_HUB_API, read with Playwright;

and compares each tab row by row. Prints a PASS/FAIL table, exits 1 on any
FAIL. Needs local port binding (run it outside a network sandbox).

    uv run python tests/parity/check_parity.py                    # ./web
    uv run python tests/parity/check_parity.py --web-ref origin/sam
    uv run python tests/parity/check_parity.py --web-dir /path/to/web

`--web-ref` git-archives that ref's web/ into a temp cache dir and `npm ci`s
it once. app.py and hub/api.py always come from THIS checkout: the parity
target is main's frozen app.py, and sam's branch has no hub/api.py.
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = "America/Vancouver"
os.environ["TZ"] = TZ  # app.py's .astimezone() uses the process zone
time.tzset()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub import db  # noqa: E402
from hub.logic import sort_items  # noqa: E402
from hub.models import Course, Item, category_for, classify_urgency, status_of  # noqa: E402

TABS = ["All", "Tasks", "Deadlines", "Materials"]
# (Show next N, Hide overdue) configurations rendered in both UIs.
CONFIGS = [(5, False), (10, False), (50, False), (50, True)]


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------
def build_fixture(path):
    """Fake data covering: overdue, soon, upcoming, done (incl. done-but-
    overdue and done-but-soon), no-due, every category, an unknown kind, 3
    courses with items (2 graded), 1 course with no items, and a Materials
    tab whose only undone dated rows are overdue (-> empty state with Hide
    overdue on). Offsets stay well clear of urgency/status thresholds so the
    seconds between the two renders can't flip a label."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    d, h = timedelta(days=1), timedelta(hours=1)
    courses = [
        Course(code="CPSC 110", section="101", term="2026W1", title="Computation, Programs, and Programming", grade=88.5),
        Course(code="MATH 101", section="102", term="2026W1", title="Integral Calculus", grade=72.0),
        Course(code="PHYS 117", section="L1A", term="2026W1", title="Dynamics and Waves", grade=None),
        Course(code="ENGL 112", section="001", term="2026W1", title="Strategies for University Writing", grade=None),
    ]
    rows = [  # course, kind, title, due offset (None = no due), done
        ("CPSC 110", "assignment", "Problem Set 4", -2 * d, None),
        ("CPSC 110", "quiz", "Quiz 3", 20 * h, None),
        ("CPSC 110", "exam", "Midterm 2", 5 * d, None),
        ("CPSC 110", "assignment", "Problem Set 3", -5 * d, True),  # done + overdue
        ("CPSC 110", "reading", "Read ch. 7", -1 * d, False),  # overdue material
        ("CPSC 110", "assignment", "Project proposal", 4 * d, False),
        ("CPSC 110", "assignment", "Draft outline", None, None),  # no due
        ("MATH 101", "assignment", "WeBWorK 8", 30 * h, None),
        ("MATH 101", "exam", "Final exam", 12 * d, None),
        ("MATH 101", "quiz", "Quiz 5", -3 * h, None),  # overdue deadline
        ("MATH 101", "assignment", "WeBWorK 7", 2 * h, True),  # done + soon
        ("MATH 101", "reading", "Textbook 5.2", None, None),  # no-due material
        ("MATH 101", "assignment", "Practice set (optional)", 1 * d, None),
        ("PHYS 117", "assignment", "Lab report 2", 3 * d, None),
        ("PHYS 117", "announcement", "Office hours moved", 6 * d, None),
        ("PHYS 117", "event", "Reading break", 9 * d, None),
        ("PHYS 117", "assignment", "Homework 6", 7 * h, None),
        ("PHYS 117", "textbook", "Buy lab manual", -4 * d, None),  # overdue material
        ("PHYS 117", "reading", "Slides wk3", 1 * d, True),  # done material
        ("PHYS 117", "quiz", "Quiz 2", 15 * d, None),
        ("PHYS 117", "lab", "Lab 4 prelab", 2 * d + 6 * h, None),  # unknown kind -> task
    ]
    items = [Item(course=c, category=category_for(k), kind=k, title=t, due=None if off is None else now + off,
                  url=f"https://example.invalid/parity/{i}", source="parity", done=done)
             for i, (c, k, t, off, done) in enumerate(rows)]
    if path.exists():
        path.unlink()
    conn = db.connect(path)
    db.save(conn, courses, items)
    conn.close()
    return items


def key(course, what, kind, link):
    return (course, what, kind, link)


def fmt_due(dt):
    """The instant as web/'s formatDue() prints it (en-US, to the minute)."""
    dt = dt.astimezone()
    return f"{dt:%a}, {dt:%b} {dt.day}, {dt.hour % 12 or 12}:{dt:%M} {dt:%p}"


def fmt_due_streamlit(dt):
    """What app.py's DatetimeColumn(format="ddd MMM D, h:mm a") shows."""
    dt = dt.astimezone()
    return f"{dt:%a} {dt:%b} {dt.day}, {dt.hour % 12 or 12}:{dt:%M} {dt:%p}".replace("AM", "am").replace("PM", "pm")


def norm_ws(s):
    return re.sub(r"\s+", " ", s.replace(" ", " ").replace(" ", " ")).strip()


# --------------------------------------------------------------------------
# app.py via AppTest
# --------------------------------------------------------------------------
def render_app(fixture):
    import logging

    import streamlit.deprecation_util
    from streamlit.testing.v1 import AppTest

    # hush app.py's use_container_width deprecation, logged once per table per run
    streamlit.deprecation_util._LOGGER.addFilter(lambda r: r.levelno >= logging.ERROR)
    db.connect.__defaults__ = (fixture,)  # app.py calls db.connect() with no args
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    sample = [t for t in at.sidebar.toggle if t.label == "Sample data"]
    meta = {"tabs": [t.label for t in at.tabs], "sample_toggle": bool(sample),
            "sample_default": sample[0].value if sample else None}
    sample[0].set_value(False).run()
    out = {}
    for n, hide in CONFIGS:
        at.sidebar.slider[0].set_value(n)
        [t for t in at.sidebar.toggle if t.label == "Hide overdue"][0].set_value(hide)
        at.run()
        assert not at.exception, at.exception
        for tab in at.tabs:
            if tab.dataframe:
                rows = []
                for r in tab.dataframe[0].value.to_dict("records"):
                    due = r["Due"].to_pydatetime()
                    rows.append({"key": key(r["Course"], r["What"], r["Kind"], r["Link"]), "urgency": r["Urgency"],
                                 "due": fmt_due(due), "due_display": fmt_due_streamlit(due)})
                out[(tab.label, n, hide)] = {"rows": rows, "empty": None}
            else:
                out[(tab.label, n, hide)] = {"rows": [], "empty": tab.info[0].value if tab.info else None}
    return meta, out


# --------------------------------------------------------------------------
# web/ via hub.api + next dev + Playwright
# --------------------------------------------------------------------------
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url, timeout, proc):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{url}: server exited ({proc.returncode}); rerun with --keep-logs")
        try:
            with urllib.request.urlopen(url, timeout=10):
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for {url}; rerun with --keep-logs")


def prepare_web(args):
    if args.web_dir:
        web = Path(args.web_dir).resolve()
    elif args.web_ref:
        sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", args.web_ref], text=True).strip()
        web = Path(tempfile.gettempdir()) / "hub-parity-web" / sha[:12] / "web"
        if not web.exists():
            web.parent.mkdir(parents=True, exist_ok=True)
            archive = subprocess.run(["git", "-C", str(ROOT), "archive", sha, "web"],
                                     check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", str(web.parent)], input=archive, check=True)
        print(f"web/ from {args.web_ref} ({sha[:12]})")
    else:
        web = ROOT / "web"
    if not (web / "node_modules").exists():
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=web, check=True)
    return web


def set_range(page, value):
    # React listens for `input`; set through the native setter so it notices.
    page.eval_on_selector("input[type=range]", """(el, v) => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, String(v));
        el.dispatchEvent(new Event('input', {bubbles: true}));
    }""", value)


def read_items(scope):
    trs = scope.locator("table tbody tr")
    if trs.count() == 0:
        empty = scope.locator("p.empty")
        return {"rows": [], "empty": norm_ws(empty.first.inner_text()) if empty.count() else None}
    rows = []
    js = "trs => trs.map(tr => [...tr.cells].map(td => [td.innerText, td.querySelector('a')?.href ?? null]))"
    for urgency, due, course, what, kind, link in trs.evaluate_all(js):
        rows.append({"key": key(course[0], what[0], kind[0], link[1]), "urgency": urgency[0].strip(),
                     "due": norm_ws(due[0]), "due_display": norm_ws(due[0])})
    return {"rows": rows, "empty": None}


def render_web(fixture, web, keep_logs):
    from playwright.sync_api import sync_playwright

    api_port, web_port = free_port(), free_port()
    origin = f"http://localhost:{web_port}"
    # hub.api's CORS allow-list is its one hard-coded dev origin (:3000);
    # point it at our port so the harness doesn't need :3000 free.
    api_code = ("from pathlib import Path; from hub import db, api; "
                f"db.connect.__defaults__ = (Path({str(fixture)!r}),); api.ALLOWED_ORIGIN = {origin!r}; "
                f"api.serve({api_port})")
    logdir = Path(tempfile.mkdtemp(prefix="hub-parity-logs-"))
    api_log, web_log = open(logdir / "api.log", "w"), open(logdir / "web.log", "w")
    api = subprocess.Popen([sys.executable, "-c", api_code], cwd=ROOT, stdout=api_log, stderr=subprocess.STDOUT)
    env = {**os.environ, "NEXT_PUBLIC_HUB_API": f"http://127.0.0.1:{api_port}", "NEXT_TELEMETRY_DISABLED": "1"}
    nxt = subprocess.Popen(["npx", "next", "dev", "--port", str(web_port), "--hostname", "localhost"],
                           cwd=web, env=env, stdout=web_log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        wait_http(f"http://127.0.0.1:{api_port}/api/courses", 30, api)
        wait_http(origin, 240, nxt)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(timezone_id=TZ, locale="en-US").new_page()
            meta = {"sample_toggle": False, "sample_default": None}
            with page.expect_response(lambda r: "/api/upcoming" in r.url, timeout=240_000) as first:
                page.goto(origin, wait_until="domcontentloaded", timeout=240_000)
                page.locator(".tabs button").first.wait_for(timeout=240_000)
                page.wait_for_load_state("networkidle")
                sample = page.get_by_label("Sample data")
                if sample.count():  # sam: local mode starts in Sample, like app.py
                    meta.update(sample_toggle=True, sample_default=sample.is_checked())
                    sample.set_checked(False)
            assert first.value.ok, f"/api/upcoming -> {first.value.status}"
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)  # let React commit the fetched rows
            meta["tabs"] = [t.strip() for t in page.locator(".tabs button").all_inner_texts()]
            out = {}
            for n, hide in CONFIGS:
                page.locator(".tabs button", has_text=re.compile("^All$")).click()
                set_range(page, n)
                page.get_by_label("Hide overdue").set_checked(hide)
                for tab in TABS:
                    page.locator(".tabs button", has_text=re.compile(f"^{tab}$")).click()
                    out[(tab, n, hide)] = read_items(page.locator("main"))
            page.locator(".tabs button", has_text=re.compile("^Courses$")).click()
            page.wait_for_timeout(200)
            meta["courses"] = [{"h2": norm_ws(card.locator("h2").inner_text()),
                                "title": norm_ws(card.locator(".course-title").inner_text()),
                                "meta": norm_ws(card.locator(".course-meta").inner_text()), **read_items(card)}
                               for card in page.locator(".course-card").all()]
            browser.close()
        return meta, out
    finally:
        try:
            os.killpg(nxt.pid, 15)
        except ProcessLookupError:
            pass
        api.terminate()
        for proc in (nxt, api):
            proc.wait(timeout=20)
        api_log.close()
        web_log.close()
        if keep_logs:
            print(f"server logs: {logdir}")


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.cells, self.details = {}, []

    def add(self, item, col, ok, detail="", warn=False):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        self.cells[(item, col)] = status
        if not ok:
            self.details.append(f"[{status}] {item} / {col}: {detail}")

    def failed(self):
        return "FAIL" in self.cells.values()

    def print(self):
        items = list(dict.fromkeys(i for i, _ in self.cells))
        cols = list(dict.fromkeys(c for _, c in self.cells))
        w = max(len(i) for i in items) + 2
        print("\n" + "Checklist item".ljust(w) + "".join(c.ljust(11) for c in cols))
        print("-" * (w + 11 * len(cols)))
        for i in items:
            print(i.ljust(w) + "".join(self.cells.get((i, c), "").ljust(11) for c in cols))
        if self.details:
            print("\nDetails:")
            for d in self.details:
                print("  " + d)


def keys(view):
    return [r["key"] for r in view["rows"]]


def short(ks):
    return [k[1] for k in ks]


def compare_tabs(rep, app, web, hidden):
    for tab in TABS:
        a50, w50 = app[(tab, 50, False)], web[(tab, 50, False)]
        ak, wk = keys(a50), keys(w50)
        rep.add("Row set", tab, set(ak) == set(wk),
                f"app-only {short(set(ak) - set(wk))}, web-only {short(set(wk) - set(ak))}")
        rep.add("Order", tab, ak == wk, f"app {short(ak)} | web {short(wk)}")
        am, wm = {r["key"]: r for r in a50["rows"]}, {r["key"]: r for r in w50["rows"]}
        common = [k for k in ak if k in wm]
        for item, field, warn in [("Urgency text (case-sensitive)", "urgency", False),
                                  ("Due (instant, to the minute)", "due", False),
                                  ("Due display format (cosmetic)", "due_display", True)]:
            bad = [(k[1], am[k][field], wm[k][field]) for k in common if am[k][field] != wm[k][field]]
            rep.add(item, tab, not bad, f"(what, app, web) {bad[:3]}", warn=warn)
        a_on, w_on = app[(tab, 50, True)], web[(tab, 50, True)]
        a_over, w_over = set(ak) - set(keys(a_on)), set(wk) - set(keys(w_on))
        rep.add("Overdue set (Hide overdue off minus on)", tab, a_over == w_over,
                f"app {sorted(short(a_over))} | web {sorted(short(w_over))}")
        rep.add("Hide overdue ON: rows+order", tab, keys(a_on) == keys(w_on),
                f"app {short(keys(a_on))} | web {short(keys(w_on))}")
        shown = {k for side in (app, web) for (t, _, _), v in side.items() if t == tab for k in keys(v)}
        leaked = shown & hidden
        rep.add("Done / no-due never shown", tab, not leaked, f"leaked {short(leaked)}")
        for n in (5, 10):
            a, w = keys(app[(tab, n, False)]), keys(web[(tab, n, False)])
            rep.add(f"Show next {n}", tab, a == w and len(a) == min(n, len(ak)), f"app {short(a)} | web {short(w)}")
        empties = [(cfg, app[(tab, *cfg)]["empty"], web[(tab, *cfg)]["empty"]) for cfg in CONFIGS
                   if app[(tab, *cfg)]["empty"] is not None or web[(tab, *cfg)]["empty"] is not None]
        if empties:
            bad = [e for e in empties if e[1] != e[2]]
            rep.add("Empty state text", tab, not bad,
                    "; ".join(f"N={c[0]} hide={c[1]}: app {a!r} | web {w!r}" for c, a, w in bad))
        else:
            rep.cells[("Empty state text", tab)] = "n/a"


def compare_courses(rep, cards_list, fixture):
    """app.py has no Courses tab, so the reference is hub.db itself, shown the
    way app.py shows rows: sort_items order, done hidden, Urgency capitalised."""
    c = "Courses"
    conn = db.connect(fixture)
    now = datetime.now(timezone.utc)
    expected, grouped = db.courses(conn), db.by_course(conn)
    cards = {card["h2"][: -len(card["title"])].strip() if card["title"] else card["h2"]: card for card in cards_list}
    rep.add("Courses: same course set (vs hub.db)", c, set(cards) == {e[0] for e in expected},
            f"db {[e[0] for e in expected]} | web {list(cards)}")
    bad_meta, bad_rows, bad_urg = [], [], []
    for code, term, title, grade in expected:
        card = cards.get(code)
        if not card:
            continue
        m = re.search(r"Grade: (\S+)", card["meta"])
        want_grade = "—" if grade is None else f"{grade:g}%"
        if card["title"] != title or term not in card["meta"] or (m and m.group(1)) != want_grade:
            bad_meta.append((code, card["title"], card["meta"], f"want grade {want_grade}"))
        rows = [r for r in grouped.get(code, [])
                if status_of(Item(r[0], r[1], r[2], r[3], datetime.fromisoformat(r[4]), r[5], "",
                                  None if r[6] is None else bool(r[6])), now) != "done"]
        rows = sort_items(rows, now)
        want = [key(r[0], r[3], r[2], r[5]) for r in rows]
        if keys(card) != want:
            bad_rows.append((code, short(want), short(keys(card))))
        for r, got in zip(rows, card["rows"]):
            u = classify_urgency(r[3], datetime.fromisoformat(r[4]), now).capitalize()
            if got["urgency"] != u:
                bad_urg.append((code, r[3], u, got["urgency"]))
    rep.add("Courses: title/term/grade", c, not bad_meta, f"{bad_meta}")
    rep.add("Courses: per-course rows+order", c, not bad_rows, f"(code, expected, web) {bad_rows}")
    rep.add("Courses: Urgency text", c, not bad_urg, f"(code, what, expected, web) {bad_urg[:3]}")


def compare(app_meta, app, web_meta, web, items, fixture):
    rep = Report()
    hidden = {key(i.course, i.title, i.kind, i.url) for i in items if i.done or i.due is None}
    compare_tabs(rep, app, web, hidden)
    g = "Global"
    rep.add("Tabs: app.py's, in order, + Courses", g,
            web_meta["tabs"][: len(app_meta["tabs"])] == app_meta["tabs"] and "Courses" in web_meta["tabs"],
            f"app {app_meta['tabs']} | web {web_meta['tabs']}")
    rep.add("Sample toggle present (local mode)", g, web_meta["sample_toggle"] == app_meta["sample_toggle"],
            f"app {app_meta['sample_toggle']} | web {web_meta['sample_toggle']}")
    rep.add("Sample toggle defaults ON", g, web_meta["sample_default"] == app_meta["sample_default"],
            f"app {app_meta['sample_default']} | web {web_meta['sample_default']}")
    compare_courses(rep, web_meta["courses"], fixture)
    return rep


def main():
    ap = argparse.ArgumentParser(description="web/ vs app.py parity oracle (#31)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--web-dir", help="web/ directory to test (default: this checkout's web/)")
    src.add_argument("--web-ref", help="git ref whose web/ to test, e.g. origin/sam")
    ap.add_argument("--keep-logs", action="store_true", help="keep the hub.api / next dev logs")
    args = ap.parse_args()

    fixture = Path(tempfile.mkdtemp(prefix="hub-parity-")) / "hub.db"
    items = build_fixture(fixture)
    web_dir = prepare_web(args)
    print(f"fixture {fixture} ({len(items)} items); rendering app.py ...")
    app_meta, app = render_app(fixture)
    print(f"rendering web/ at {web_dir} ...")
    web_meta, web = render_web(fixture, web_dir, args.keep_logs)
    rep = compare(app_meta, app, web_meta, web, items, fixture)
    rep.print()
    print("\nRESULT:", "FAIL" if rep.failed() else "PASS", "(WARN rows don't affect the exit code)")
    sys.exit(1 if rep.failed() else 0)


if __name__ == "__main__":
    main()
