"""UI regression oracle: does a candidate UI behave like the demo baseline?

Opt-in, not part of `uv run pytest` (the file isn't named test_*.py).

Baseline: git tag demo-2026-09-27's web/, served with `next dev` in local
mode (NEXT_PUBLIC_HUB_API) against a fixture hub.db via hub.api.
Each side's hub.api comes from its own ref's hub/ (the candidate's
can be overridden with --candidate-hub; a URL/dir side uses this checkout's),
on the same fixture rows (one shared DB unless the hub.db schemas differ).
Candidate: a URL, a git ref (its web/ is extracted and npm-installed
in a temp cache dir) or a directory (a web/ dir or a repo root holding one).
If the candidate can't be pointed at hub.api (a hosted URL, a non-Next
export), both sides are compared in Sample mode instead.

Everything is located by accessible role/name/text, never by CSS class, so a
Figma rewrite with different markup passes as long as it behaves the same.
Behavioural checks FAIL on any difference from the baseline; the visual
report (screenshots, horizontal scroll, button-label contrast) only WARNs.
The browser clock (and hub.api's clock) is frozen at one instant, so both
renders see identical urgency, status and sample due dates.

    uv run python tests/regression/check_ui_regression.py --candidate origin/sam
    uv run python tests/regression/check_ui_regression.py --candidate ../figma-export
    uv run python tests/regression/check_ui_regression.py --candidate https://example.figma.site

Needs local port binding and (first run per ref) npm registry access.
Exit code 1 on any FAIL.
"""
import argparse
import dataclasses
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = "America/Vancouver"
os.environ["TZ"] = TZ
time.tzset()

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hub import db  # noqa: E402
from hub.models import Course, Item, category_for  # noqa: E402

BASELINE_REF = "demo-2026-09-27"
ITEM_TABS = ["All", "Tasks", "Deadlines", "Materials"]
ALL_TABS = ITEM_TABS + ["Courses"]
CONFIGS = [(5, False), (10, False), (50, False), (50, True)]  # (Show next N, Hide overdue)
CONNECT = ["Connect Canvas", "Connect PrairieLearn"]
VIEWPORTS = {"desktop": (1280, 800), "tablet": (768, 1024), "mobile": (375, 812)}
# Baseline tab label -> candidate label, tried after the baseline's own label.
# Default: the "Gather" redesign (PR #45) renamed the nav.
TAB_ALIAS_DEFAULT = "All=Overview,Tasks=Assignments,Deadlines=Calendar"
TAB_ALIAS = {}
WAIT_MS = 30_000  # cap on any wait for an element; a miss becomes a finding
URGENCY = {"overdue", "critical", "high", "medium", "low"}
FIELDS = ("course", "what", "kind")
NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
CACHE = Path(tempfile.gettempdir()) / "hub-ui-regression"
# The demo baseline's Connect buttons set background:#fff but no color, so in
# the dark scheme they inherit light `buttontext`: white on white.
KNOWN_BASELINE_DEFECT = "(known baseline defect: white-on-white Connect buttons in the dark scheme)"


# --------------------------------------------------------------------------
# Fixture (from tests/parity/check_parity.py on oracle/parity)
# --------------------------------------------------------------------------
def build_fixture(path):
    """Overdue, soon, upcoming, done (incl. done-but-overdue), no-due, every
    category, an unknown kind, graded/ungraded courses and one with no items."""
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
        ("CPSC 110", "assignment", "Problem Set 3", -5 * d, True),
        ("CPSC 110", "reading", "Read ch. 7", -1 * d, False),
        ("CPSC 110", "assignment", "Project proposal", 4 * d, False),
        ("CPSC 110", "assignment", "Draft outline", None, None),
        ("MATH 101", "assignment", "WeBWorK 8", 30 * h, None),
        ("MATH 101", "exam", "Final exam", 12 * d, None),
        ("MATH 101", "quiz", "Quiz 5", -3 * h, None),
        ("MATH 101", "assignment", "WeBWorK 7", 2 * h, True),
        ("MATH 101", "reading", "Textbook 5.2", None, None),
        ("MATH 101", "assignment", "Practice set (optional)", 1 * d, None),
        ("PHYS 117", "assignment", "Lab report 2", 3 * d, None),
        ("PHYS 117", "announcement", "Office hours moved", 6 * d, None),
        ("PHYS 117", "event", "Reading break", 9 * d, None),
        ("PHYS 117", "assignment", "Homework 6", 7 * h, None),
        ("PHYS 117", "textbook", "Buy lab manual", -4 * d, None),
        ("PHYS 117", "reading", "Slides wk3", 1 * d, True),
        ("PHYS 117", "quiz", "Quiz 2", 15 * d, None),
        ("PHYS 117", "lab", "Lab 4 prelab", 2 * d + 6 * h, None),
    ]
    items = [Item(course=c, category=category_for(k), kind=k, title=t, due=None if off is None else NOW + off,
                  url=f"https://example.invalid/regression/{i}", source="regression", done=done)
             for i, (c, k, t, off, done) in enumerate(rows)]
    conn = db.connect(path)
    db.save(conn, courses, items)
    conn.close()
    return courses, items


SEED = ("import json, sys\nfrom datetime import datetime\nfrom pathlib import Path\nfrom hub import db\n"
        "from hub.models import Course, Item\nd = json.load(sys.stdin)\n"
        "items = [Item(**{**i, 'due': i['due'] and datetime.fromisoformat(i['due'])}) for i in d['items']]\n"
        "conn = db.connect(Path(sys.argv[1]))\ndb.save(conn, [Course(**c) for c in d['courses']], items)\nconn.close()\n")


def schema(path):
    with sqlite3.connect(path) as c:
        return c.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()


def fixture_for(hub_root, fixture, courses, items):
    """The shared fixture if hub_root's hub.db has its schema, else a DB seeded
    from the same rows with hub_root's own hub.db."""
    if hub_root == ROOT:
        return fixture
    path = Path(tempfile.mkdtemp(prefix="hub-ui-regression-db-")) / "hub.db"
    rows = {"courses": [dataclasses.asdict(c) for c in courses],
            "items": [{**dataclasses.asdict(i), "due": i.due and i.due.isoformat()} for i in items]}
    subprocess.run([sys.executable, "-c", SEED, str(path)], cwd=hub_root, input=json.dumps(rows), text=True, check=True)
    return fixture if schema(path) == schema(fixture) else path


# --------------------------------------------------------------------------
# Targets: resolve, install, serve
# --------------------------------------------------------------------------
def git_tree(ref, sub="web"):
    """ref's `sub` dir, extracted once into CACHE/<sha>/ -> (path, label)."""
    sha = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", f"{ref}^{{commit}}"], text=True).strip()
    out = CACHE / sha[:12] / sub
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tar = subprocess.run(["git", "-C", str(ROOT), "archive", sha, sub], check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(out.parent)], input=tar, check=True)
    return out, f"{ref} ({sha[:12]})"


def resolve(spec):
    """-> dict(kind=url|dir, where=URL or Path, label, server=next|vite|static|None, ref=git ref|None)."""
    if re.match(r"https?://", spec):
        return {"kind": "url", "where": spec, "label": spec, "server": None, "ref": None}
    p, ref = Path(spec).expanduser(), None
    if p.is_dir():
        web = p / "web" if (p / "web" / "package.json").exists() else p
        label = str(web.resolve())
    else:
        (web, label), ref = git_tree(spec), spec
    web = web.resolve()
    pkg = json.loads((web / "package.json").read_text()) if (web / "package.json").exists() else {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    server = "next" if "next" in deps else "vite" if "vite" in deps else "static" if (web / "index.html").exists() else None
    if server is None:
        sys.exit(f"{web}: no Next/Vite package.json or index.html; serve it yourself and pass its URL")
    if pkg and not (web / "node_modules").exists():
        cmd = "ci" if (web / "package-lock.json").exists() else "install"
        subprocess.run(["npm", cmd, "--no-audit", "--no-fund"], cwd=web, check=True)
    return {"kind": "dir", "where": web, "label": label, "server": server, "ref": ref}


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


class Served:
    """Context manager: hub.api (local mode only, from hub_root/hub) + the target's dev server."""

    def __init__(self, target, local, fixture, logdir, hub_root=ROOT):
        self.t, self.local, self.fixture, self.logdir, self.procs = target, local, fixture, logdir, []
        self.hub_root = hub_root

    def _spawn(self, name, cmd, **kw):
        log = open(self.logdir / f"{name}.log", "w")
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, **kw)
        self.procs.append((proc, log))
        return proc

    def __enter__(self):
        if self.t["kind"] == "url":
            return self.t["where"]
        port = free_port()
        host = "127.0.0.1" if self.t["server"] == "static" else "localhost"
        origin = f"http://{host}:{port}"
        env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
        if self.local:
            api_port = free_port()
            # Frozen clock, fixture DB, and CORS allow-list patched to our origin
            # (hub.api only reflects its one hard-coded dev origin, :3000).
            code = (
                "import datetime as _dt\nfrom pathlib import Path\nfrom hub import db, api\n"
                f"FIXED = _dt.datetime.fromisoformat({NOW.isoformat()!r})\n"
                "class _Frozen(_dt.datetime):\n"
                "    @classmethod\n"
                "    def now(cls, tz=None):\n"
                "        return FIXED.astimezone(tz) if tz else FIXED\n"
                "api.datetime = _Frozen\n"
                f"db.connect.__defaults__ = (Path({str(self.fixture)!r}),)\n"
                f"api.ALLOWED_ORIGIN = {origin!r}\napi.serve({api_port})\n")
            api = self._spawn("api", [sys.executable, "-c", code], cwd=self.hub_root)
            wait_http(f"http://127.0.0.1:{api_port}/api/courses", 30, api)
            env["NEXT_PUBLIC_HUB_API"] = env["VITE_HUB_API"] = f"http://127.0.0.1:{api_port}"
        cmd = {"next": ["npx", "next", "dev", "--port", str(port), "--hostname", host],
               "vite": ["npx", "vite", "--port", str(port), "--strictPort", "--host", host],
               "static": [sys.executable, "-m", "http.server", str(port), "--bind", host]}[self.t["server"]]
        web = self._spawn("web", cmd, cwd=self.t["where"], env=env)
        try:
            wait_http(origin, 240, web)
        except RuntimeError as e:
            tail = (self.logdir / "web.log").read_text()[-1500:]
            raise RuntimeError(f"{e}\n--- {self.t['server']} log tail ---\n{tail}") from None
        return origin

    def __exit__(self, *exc):
        for proc, log in self.procs:
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                pass
            proc.wait(timeout=20)
            log.close()


# --------------------------------------------------------------------------
# Extraction (roles / accessible names / text only)
# --------------------------------------------------------------------------
CELL_SEL = "th,td,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]"
ROW_FN = f"""r => {{
  const cells = [...r.querySelectorAll('{CELL_SEL}')];
  const hdr = c => c.getAttribute('role') === 'columnheader' || (c.tagName === 'TH' && !!c.closest('thead'));
  return {{header: cells.length > 0 && cells.every(hdr),
          cells: cells.map(c => ({{text: c.innerText, href: c.querySelector('a[href]')?.href ?? null}}))}};
}}"""
# Row elements under root, most accessible structure first: table rows, then
# list items holding a link, then the largest container of each "Open" link.
FIND_ROWS = """root => {
  const vis = el => el.getClientRects().length > 0;
  const trs = [...root.querySelectorAll('tr,[role=row]')].filter(vis);
  if (trs.length) return trs;
  const lis = [...root.querySelectorAll('li,[role=listitem]')].filter(li => vis(li) && li.querySelector('a[href]'));
  if (lis.length) return lis;
  const isOpen = a => /^\\s*open\\s*$/i.test(a.getAttribute('aria-label') || a.innerText || '');
  const opens = el => [...el.querySelectorAll('a[href]')].filter(isOpen).length;
  return [...root.querySelectorAll('a[href]')].filter(a => isOpen(a) && vis(a)).map(a => {
    let el = a;
    while (el.parentElement && el.parentElement !== root && opens(el.parentElement) === 1) el = el.parentElement;
    return el;
  });
}"""
PIECES_FN = """r => ({pieces: r.innerText.split(/\\n|·/).map(s => s.trim()).filter(Boolean),
               href: [...r.querySelectorAll('a[href]')].find(a => /^\\s*open\\s*$/i.test(a.getAttribute('aria-label') || a.innerText || ''))?.href
                     ?? r.querySelector('a[href]')?.href ?? null})"""
ROWS_JS = f"""root => {{
  const rowFn = {ROW_FN}, piecesFn = {PIECES_FN};
  return ({FIND_ROWS})(root).map(r => (r.tagName === 'TR' || r.getAttribute('role') === 'row') ? rowFn(r) : piecesFn(r));
}}"""
COURSES_JS = f"""root => {{
  const rowFn = {ROW_FN}, piecesFn = {PIECES_FN};
  const rowEls = ({FIND_ROWS})(root), rowSet = new Set(rowEls);
  const inRow = el => {{ for (let e = el; e && e !== root; e = e.parentElement) if (rowSet.has(e)) return e; return null; }};
  const CODE = /^\\s*([A-Z]{{2,5}}\\s?\\d{{3}}[A-Z]?)\\b/;
  const out = []; let cur = null;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  for (let el = w.currentNode; el; el = w.nextNode()) {{
    const heading = /^H[1-6]$/.test(el.tagName) || el.getAttribute('role') === 'heading';
    const own = [...el.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
    const m = (heading || (own && own === [...el.childNodes].find(n => n.nodeType === 3 ? n.textContent.trim() : n.nodeType === 1)
                           && CODE.test(own.textContent)))
              && !el.closest('button,[role=button]') && !inRow(el) && el.innerText.match(CODE);
    if (m) {{ cur = {{code: m[1], heading: el.innerText, text: [], rows: []}}; out.push(cur); continue; }}
    if (!cur) continue;
    if (rowSet.has(el)) {{ cur.rows.push(el.tagName === 'TR' || el.getAttribute('role') === 'row' ? rowFn(el) : piecesFn(el)); continue; }}
    if (inRow(el) || el.closest('table,[role=table],[role=grid]')) continue;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) cur.text.push(n.textContent);
  }}
  return out;
}}"""
CONTRAST_JS = """() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const ctx = cv.getContext('2d', {willReadFrequently: true});
  const rgba = s => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = s; ctx.fillRect(0, 0, 1, 1);
                      const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (top, bot) => top.slice(0, 3).map((c, i) => c * top[3] + bot[i] * (1 - top[3]));
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const bgOf = el => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = dark ? [18, 18, 18] : [255, 255, 255];
    for (const l of layers.reverse()) bg = over(l, bg);
    return bg;
  };
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
                     return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  return [...document.querySelectorAll('button,[role=button],[role=tab]')]
    .filter(el => el.getClientRects().length && (el.innerText || '').trim())
    .map(el => { const bg = bgOf(el), fg = over(rgba(getComputedStyle(el).color), bg);
                 const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
                 return {name: el.innerText.trim(), ratio: Math.round((a + 0.05) / (b + 0.05) * 100) / 100,
                         fg: fg.map(Math.round), bg: bg.map(Math.round)}; });
}"""

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def norm_ws(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ").replace("\xa0", " ")).strip()


def parse_due(text):
    """Any reasonable rendering of a due time -> 'MM-DD HH:MM' (display zone),
    so a Figma UI may format dates differently and still match the instant."""
    t = norm_ws(text)
    m = re.search(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)", t)
    if m:
        return f"{m[2]}-{m[3]} {m[4]}:{m[5]}"
    mon = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?", t, re.I)
    tm = re.search(r"\b(\d{1,2}):(\d\d)\s*(?:([ap])\.?m\.?)?", t, re.I)
    if not (mon and tm):
        return f"unparsed:{t}"
    rest = (t[:mon.start()] + " " + t[mon.end():]).replace(tm.group(0), " ")
    day = re.search(r"\b(\d{1,2})\b", rest)
    hour = int(tm[1]) % 12 + (12 if tm[3].lower() == "p" else 0) if tm[3] else int(tm[1])
    return f"{MONTHS[mon[1].lower()]:02d}-{int(day[1]) if day else 0:02d} {hour:02d}:{tm[2]}"


CODE_RE = re.compile(r"^[A-Z]{2,5} ?\d{3}[A-Z]?$")


def parse_pieces(r, course_hint=None):
    """A non-table row's text pieces -> the same fields a table row gives.
    Course = a course-code piece, due = a parseable date, urgency = an urgency
    word, kind = a bare lowercase word, what = the first piece left over (a
    short prefix of the course code is a badge, not the title). Fields a row
    doesn't show stay None."""
    ps = [p for p in r["pieces"] if not re.fullmatch(r"open|—|-", p, re.I)]
    dashes = sum(p in ("—", "-") for p in r["pieces"])
    course = next((p for p in ps if CODE_RE.match(p)), course_hint)
    due = urg = kind = what = None
    for p in ps:
        if p == course or (course and len(p) <= 3 and course.startswith(p)):
            continue
        if due is None and not parse_due(p).startswith("unparsed:"):
            due = p
        elif urg is None and p.lower() in URGENCY:
            urg = p
        elif kind is None and re.fullmatch(r"[a-z]+", p):
            kind = p
        elif what is None:
            what = p
    if dashes and urg is None:
        urg, dashes = "—", dashes - 1
    if dashes and due is None:
        due = "—"
    return {"key": (course, what, kind), "urgency": urg, "due": parse_due(due or ""), "href": r["href"]}


def parse_rows(raw, course=None):
    """Raw rows (ROW_FN table rows or PIECES_FN rows) -> {'rows': [{key,
    urgency, due, href}]}, table rows keyed by header text (column order is
    free), or {'error': ...}."""
    cols, rows = None, []
    for r in raw:
        if "pieces" in r:
            rows.append(parse_pieces(r, course))
            continue
        cells = r["cells"]
        if r["header"]:
            cols = {norm_ws(c["text"]).lower(): i for i, c in enumerate(cells)}
            continue
        if cols is None:
            return {"error": "table has no column headers"}

        def text(name):
            i = cols.get(name)
            return norm_ws(cells[i]["text"]) if i is not None and i < len(cells) else None
        i = cols.get("link")
        href = cells[i]["href"] if i is not None and i < len(cells) else next((c["href"] for c in cells if c["href"]), None)
        rows.append({"key": (text("course"), text("what"), text("kind")), "urgency": text("urgency"),
                     "due": parse_due(text("due") or ""), "href": href})
    return {"rows": rows}


def control(page, roles, name):
    pat = re.compile(name, re.I) if isinstance(name, str) else name
    for role in roles:
        loc = page.get_by_role(role, name=pat)
        if loc.count():
            return loc.first
    loc = page.get_by_label(pat)
    return loc.first if loc.count() else None


def tab_control(page, name):
    """The baseline label first, then its --tab-alias."""
    for label in dict.fromkeys([name, TAB_ALIAS.get(name, name)]):
        ctl = control(page, ("tab", "button", "link", "radio"), re.compile(rf"^\s*{re.escape(label)}\s*$"))
        if ctl is not None:
            return ctl
    return None


def tab_label(page, name):
    ctl = tab_control(page, name)
    return None if ctl is None else norm_ws(ctl.inner_text()) or name


def poll(fn, ms=WAIT_MS, step=250):
    """fn() until truthy or ms pass; returns the last value, never raises."""
    deadline = time.time() + ms / 1000
    while True:
        try:
            v = fn()
        except Exception:
            v = None
        if v or time.time() >= deadline:
            return v
        time.sleep(step / 1000)


def set_show_next(page, n):
    ctl = control(page, ("slider", "spinbutton", "combobox"), r"show next")
    if ctl is None:
        return False
    tag = ctl.evaluate("el => el.tagName")
    if tag == "SELECT":
        ctl.select_option(str(n))
    elif tag == "INPUT":  # native setter so React notices the change
        ctl.evaluate("""(el, v) => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, String(v));
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""", n)
    else:  # custom ARIA slider: drive it by keyboard
        ctl.focus()
        ctl.press("Home")
        for _ in range(100):
            if str(ctl.get_attribute("aria-valuenow")) == str(n):
                break
            ctl.press("ArrowRight")
    return True


def settle(page, ms=300):
    try:
        page.wait_for_load_state("networkidle", timeout=WAIT_MS)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def click(ctl):
    try:
        ctl.click(timeout=WAIT_MS)
        return True
    except Exception:
        return False


def extract(page, url, local, shots, label):
    # goto may wait on next dev's first compile; element waits are capped at WAIT_MS
    page.goto(url, wait_until="domcontentloaded", timeout=240_000)
    meta = {"rendered": bool(poll(lambda: any(tab_control(page, t) for t in ALL_TABS)))}
    settle(page)
    main = page.get_by_role("main")
    scope = main.first if main.count() else page.locator("body")
    sample = control(page, ("checkbox", "switch"), r"sample")
    meta["sample"] = None if sample is None else sample.is_checked()
    if sample is not None:  # compare like with like: fixture rows in local mode
        try:
            sample.set_checked(not local, timeout=WAIT_MS)
        except Exception:
            pass
        settle(page)
    if local:  # wait for the fixture rows to arrive
        poll(lambda: scope.evaluate(ROWS_JS))
    meta["tabs"] = {t: tab_label(page, t) for t in ALL_TABS}
    meta["connect"] = {}
    for name in CONNECT:
        btn = page.get_by_role("button", name=re.compile(re.escape(name), re.I))
        meta["connect"][name] = None if not btn.count() else {
            "visible": btn.first.is_visible(), "label": norm_ws(btn.first.inner_text())}
    views, meta["controls"] = {}, {}  # controls: tab -> {control name: present on that tab}
    for n, hide in CONFIGS:
        for tab in ITEM_TABS:
            ctl = tab_control(page, tab)
            if ctl is None or not click(ctl):
                views[(tab, n, hide)] = {"error": f"Tab missing: {tab}"}
                continue
            page.wait_for_timeout(100)
            has_n = set_show_next(page, n)  # controls live on (and are set on) each tab
            hide_ctl = control(page, ("checkbox", "switch"), r"hide overdue")
            if hide_ctl is not None:
                try:
                    hide_ctl.set_checked(hide, timeout=WAIT_MS)
                except Exception:
                    hide_ctl = None
            page.wait_for_timeout(100)
            meta["controls"].setdefault(tab, {"Show next": has_n, "Hide overdue": hide_ctl is not None})
            views[(tab, n, hide)] = parse_rows(scope.evaluate(ROWS_JS))  # compare() voids it if a control is missing
    meta["courses"] = None
    if tab_control(page, "Courses") and click(tab_control(page, "Courses")):
        page.wait_for_timeout(200)
        meta["courses"] = [{"code": norm_ws(c["code"]), "heading": norm_ws(c["heading"]),
                            "text": norm_ws(c["heading"] + " " + " ".join(c["text"])),
                             **parse_rows(c["rows"], norm_ws(c["code"]))}
                           for c in scope.evaluate(COURSES_JS)]
    # visual pass on the All tab, widest config, Hide overdue off
    if tab_control(page, "All") and click(tab_control(page, "All")):
        set_show_next(page, 50)
        hide_ctl = control(page, ("checkbox", "switch"), r"hide overdue")
        if hide_ctl is not None:
            try:
                hide_ctl.set_checked(False, timeout=WAIT_MS)
            except Exception:
                pass
    vis = {"hscroll": {}, "contrast": {}}
    for scheme in ("light", "dark"):
        page.emulate_media(color_scheme=scheme)
        for vp, (w, h) in VIEWPORTS.items():
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(150)
            page.screenshot(path=str(shots / f"{label}-{vp}-{scheme}.png"), full_page=True)
            if scheme == "light":
                vis["hscroll"][vp] = page.evaluate(
                    "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
        page.set_viewport_size({"width": 1280, "height": 800})
        vis["contrast"][scheme] = page.evaluate(CONTRAST_JS)
    page.emulate_media(color_scheme="light")
    return meta, views, vis


def render(target, local, fixture, shots, label, keep_logs, hub_root=ROOT):
    from playwright.sync_api import sync_playwright

    logdir = Path(tempfile.mkdtemp(prefix=f"hub-ui-regression-{label}-logs-"))
    print(f"rendering {label}: {target['label']} ({'local' if local else 'sample'} mode) ...", flush=True)
    try:
        with Served(target, local, fixture, logdir, hub_root) as url, sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(timezone_id=TZ, locale="en-US", viewport={"width": 1280, "height": 800})
            ctx.clock.set_fixed_time(NOW)
            out = extract(ctx.new_page(), url, local, shots, label)
            browser.close()
            return out
    finally:
        if keep_logs:
            print(f"  server logs: {logdir}")


# --------------------------------------------------------------------------
# Compare
# --------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.cells, self.details = {}, []

    def add(self, item, col, ok, detail="", warn=False, note=""):
        status = "PASS" if ok else ("WARN" if warn else "FAIL")
        self.cells[(item, col)] = status
        if not ok or note:
            self.details.append(f"[{status}] {item} / {col}: " + (note if ok else f"{detail} {note}".rstrip()))

    def failed(self):
        return "FAIL" in self.cells.values()

    def print(self, title, order=()):
        items = list(dict.fromkeys(i for i, _ in self.cells))
        cols = sorted(dict.fromkeys(c for _, c in self.cells), key=lambda c: order.index(c) if c in order else 99)
        w = max(len(i) for i in items) + 2
        print(f"\n{title}\n" + "Check".ljust(w) + "".join(c.ljust(11) for c in cols))
        print("-" * (w + 11 * len(cols)))
        for i in items:
            print(i.ljust(w) + "".join(self.cells.get((i, c), "").ljust(11) for c in cols))
        for d in self.details:
            print("  " + d)


def shown(view):
    """Which of FIELDS every row of a view shows (a candidate may drop one)."""
    rows = view.get("rows", [])
    return tuple(all(r["key"][i] is not None for r in rows) for i in range(len(FIELDS)))


def common_fields(b, c):
    """Fields both sides show -> (mask to compare on, fields the candidate dropped)."""
    mb, mc = shown(b), shown(c)
    return tuple(x and y for x, y in zip(mb, mc)), [f for f, x, y in zip(FIELDS, mb, mc) if x and not y]


def keys(view, mask=(True,) * len(FIELDS)):
    return [tuple(k if m else None for k, m in zip(r["key"], mask)) for r in view.get("rows", [])]


def pset(ks, mask):
    return {tuple(k if m else None for k, m in zip(key, mask)) for key in ks}


def short(ks):
    return [k[1] for k in ks]


def view_error(b, c):
    if "error" in c:
        return c["error"]
    if "error" in b:
        return f"baseline: {b['error']}"
    return None


ROW_CHECKS = ["Row set", "Order", "Urgency text (case-sensitive)", "Due instant", "Deep-link hrefs"]


def compare_rows(rep, col, b, c, hidden):
    err = view_error(b, c)
    if err:
        for i in ROW_CHECKS + ["Done items never shown"] * (hidden is not None):
            rep.add(i, col, False, err)
        return
    mask, lost = common_fields(b, c)
    rep.add("Row fields shown", col, not lost, f"candidate rows don't show {lost}; compared without them")
    bk, ck = keys(b, mask), keys(c, mask)
    rep.add("Row set", col, set(bk) == set(ck),
            f"baseline-only {short(set(bk) - set(ck))}, candidate-only {short(set(ck) - set(bk))}")
    rep.add("Order", col, bk == ck, f"baseline {short(bk)} | candidate {short(ck)}")
    bm, cm = dict(zip(bk, b["rows"])), dict(zip(ck, c["rows"]))
    common = [k for k in bk if k in cm]
    for item, field in zip(ROW_CHECKS[2:], ["urgency", "due", "href"]):
        bad = [(k[1], bm[k][field], cm[k][field]) for k in common if bm[k][field] != cm[k][field]]
        rep.add(item, col, not bad, f"(what, baseline, candidate) {bad[:3]}")
    if hidden is not None:
        leaked = set(ck) & pset(hidden, mask)
        rep.add("Done items never shown", col, not leaked, f"leaked {short(leaked)}")


def compare(bm, bv, cm, cv, hidden):
    rep = Report()
    for (tab, n, hide), v in cv.items():  # a control the baseline has on this tab but the candidate lacks
        lack = [c for c in ("Show next",) + ("Hide overdue",) * hide
                if bm["controls"].get(tab, {}).get(c) and not cm["controls"].get(tab, {}).get(c)]
        if lack and "error" not in v:
            cv[(tab, n, hide)] = {"error": f"{lack[0]} control not found on {tab}"}
    b = bv[("All", 50, False)]
    rep.add("Baseline sanity: rows extracted", "Global", bool(keys(b)),
            f"baseline All tab gave {b} - the oracle can't see the baseline's rows")
    rep.add("Candidate rendered (a tab appeared)", "Global", cm["rendered"], f"none of {ALL_TABS} within {WAIT_MS // 1000}s")
    for tab in (t for t in ITEM_TABS if bm["tabs"][t]):
        b50, c50 = bv[(tab, 50, False)], cv[(tab, 50, False)]
        compare_rows(rep, tab, b50, c50, hidden)
        bon, con = bv[(tab, 50, True)], cv[(tab, 50, True)]
        err = view_error(bon, con) or view_error(b50, c50)
        m = None if err else common_fields(bon, con)[0]
        rep.add("Hide overdue ON: rows+order", tab, not err and keys(bon, m) == keys(con, m),
                err or f"baseline {short(keys(bon, m))} | candidate {short(keys(con, m))}")
        bo = set(keys(b50, m)) - set(keys(bon, m)) if not err else set()
        co = None if err else set(keys(c50, m)) - set(keys(con, m))
        rep.add("Overdue set (off minus on)", tab, not err and bo == co,
                err or f"baseline {sorted(short(bo))} | candidate {sorted(short(co))}")
        for n in (5, 10):
            b, c = bv[(tab, n, False)], cv[(tab, n, False)]
            err = view_error(b, c)
            m = None if err else common_fields(b, c)[0]
            rep.add(f"Show next {n}", tab, not err and keys(b, m) == keys(c, m),
                    err or f"baseline {short(keys(b, m))} | candidate {short(keys(c, m))}")
    g = "Global"
    for t in ALL_TABS:
        if bm["tabs"][t]:
            got = cm["tabs"][t]
            rep.add(f"Tab present: {t}", g, bool(got), f"Tab missing: {t}",
                    note="" if not got or got == bm["tabs"][t] else f"(candidate calls it {got!r})")
    for ctl in ("Show next", "Hide overdue"):
        on = lambda m: [t for t, cs in m["controls"].items() if cs[ctl]]  # noqa: E731
        lacking = [t for t in on(bm) if t not in on(cm)]
        rep.add(f"Control present: {ctl}", g, bool(on(cm)) or not on(bm), "missing on every candidate tab",
                note=f"(candidate tabs without it: {lacking})" if lacking else "")
    desc = lambda s: "absent" if s is None else "default " + ("ON" if s else "OFF")  # noqa: E731
    extra = ("; baseline local mode shows real data by default, the candidate shows Sample data"
             " (switched OFF for the rest of the run)") if hidden is not None and cm["sample"] else ""
    rep.add("Sample toggle (presence, default)", g, bm["sample"] == cm["sample"],
            f"baseline {desc(bm['sample'])} | candidate {desc(cm['sample'])}{extra}")
    for name in CONNECT:
        b, c = bm["connect"][name], cm["connect"][name]
        if b is None:
            rep.add(f"{name} (not clicked)", g, c is None, "candidate has it, baseline doesn't")
        else:
            rep.add(f"{name} (not clicked)", g, bool(c and c["visible"] and c["label"]),
                    f"candidate {c or 'missing'} (needs a visible button with an accessible name)")
    compare_courses(rep, bm["courses"], cm["courses"], hidden)
    return rep


def compare_courses(rep, bc, cc, hidden):
    col = "Courses"
    if bc is None:
        return
    if cc is None:
        for i in ("Course codes", "Title/term/grade", "Per-course rows+order", "Per-course Urgency"):
            rep.add(i, col, False, "Courses tab missing")
        return
    bcodes, ccodes = [c["code"] for c in bc], [c["code"] for c in cc]
    rep.add("Course codes", col, bcodes == ccodes, f"baseline {bcodes} | candidate {ccodes}")
    cmap = {c["code"]: c for c in cc}

    def grade(s):
        m = re.search(r"Grade:?\s*([^\s·|]+)", s)
        return m and m[1]
    bad_meta, bad_rows, bad_urg = [], [], []
    rows = lambda cs: {"rows": [r for c in cs for r in c.get("rows", [])]}  # noqa: E731
    mask, lost = common_fields(rows(bc), rows(cc))
    rep.add("Row fields shown", col, not lost, f"candidate rows don't show {lost}; compared without them")
    for b in bc:
        c = cmap.get(b["code"])
        if not c:
            continue
        title = b["heading"][len(b["code"]):].strip()
        term = re.search(r"\b20\d\d[WS]\d?\b", b["text"])
        if title not in c["text"] or (term and term[0] not in c["text"]) or grade(b["text"]) != grade(c["text"]):
            bad_meta.append((b["code"], f"want {title!r} / {term and term[0]} / grade {grade(b['text'])}",
                             c["text"][:120]))
        if "error" in c:
            bad_rows.append((b["code"], c["error"]))
            continue
        if keys(b, mask) != keys(c, mask):
            bad_rows.append((b["code"], short(keys(b, mask)), short(keys(c, mask))))
        cu = dict(zip(keys(c, mask), (r["urgency"] for r in c["rows"])))
        bad_urg += [(b["code"], k[1], r["urgency"], cu[k]) for k, r in zip(keys(b, mask), b.get("rows", []))
                    if k in cu and cu[k] != r["urgency"]]
        if hidden is not None and set(keys(c, mask)) & pset(hidden, mask):
            bad_rows.append((b["code"], "done items shown", short(set(keys(c, mask)) & pset(hidden, mask))))
    rep.add("Title/term/grade", col, not bad_meta, f"{bad_meta}")
    rep.add("Per-course rows+order", col, not bad_rows, f"(code, baseline, candidate) {bad_rows}")
    rep.add("Per-course Urgency", col, not bad_urg, f"(code, what, baseline, candidate) {bad_urg[:3]}")


def visual(bvis, cvis):
    rep = Report()
    for side, vis in (("baseline", bvis), ("candidate", cvis)):
        for vp, (sw, cw) in vis["hscroll"].items():
            rep.add(f"No horizontal scroll @ {VIEWPORTS[vp][0]}px ({vp})", side, sw <= cw + 1,
                    f"scrollWidth {sw} > clientWidth {cw}", warn=True)
        for scheme, buttons in vis["contrast"].items():
            low = [(b["name"][:30], b["ratio"], b["fg"], b["bg"]) for b in buttons if b["ratio"] < 4.5]
            known = low and all(n.lower().startswith("connect") for n, *_ in low)
            note = "" if not known else (KNOWN_BASELINE_DEFECT if side == "baseline"
                                         else "(same as the baseline's known defect)")
            rep.add(f"Button-label contrast >= 4.5 ({scheme})", side, not low, f"(label, ratio, fg, bg) {low}",
                    warn=True, note=note)
    return rep


def main():
    ap = argparse.ArgumentParser(description="UI regression oracle vs the demo baseline")
    ap.add_argument("--baseline", default=BASELINE_REF, help=f"URL, git ref or dir (default: {BASELINE_REF})")
    ap.add_argument("--candidate", required=True, help="URL, git ref, or dir (web/ or a repo root with web/)")
    ap.add_argument("--candidate-hub", help="git ref whose hub/ serves the candidate's hub.api "
                    "(default: the candidate's ref if it is one, else this checkout)")
    ap.add_argument("--mode", choices=["auto", "local", "sample"], default="auto",
                    help="auto: local (fixture via hub.api) when both sides are Next apps we serve, else sample")
    ap.add_argument("--out", help="screenshot dir (default: a new temp dir)")
    ap.add_argument("--keep-logs", action="store_true", help="print where the server logs are")
    ap.add_argument("--tab-alias", default=TAB_ALIAS_DEFAULT,
                    help=f"baseline=candidate tab labels, tried after the baseline label (default: {TAB_ALIAS_DEFAULT}; '' for none)")
    args = ap.parse_args()
    TAB_ALIAS.update(kv.split("=", 1) for kv in args.tab_alias.split(",") if "=" in kv)

    base, cand = resolve(args.baseline), resolve(args.candidate)
    local = args.mode == "local" or (args.mode == "auto" and base["server"] == cand["server"] == "next")
    out = Path(args.out or tempfile.mkdtemp(prefix="hub-ui-regression-out-"))
    out.mkdir(parents=True, exist_ok=True)
    fixture, bfixture, cfixture, hidden = None, None, None, None
    hub_ref = args.candidate_hub or cand["ref"]
    bhub, chub = (git_tree(r, "hub")[0].parent if r else ROOT for r in (base["ref"], hub_ref))
    if local:
        fixture = Path(tempfile.mkdtemp(prefix="hub-ui-regression-db-")) / "hub.db"
        courses, items = build_fixture(fixture)
        hidden = {(i.course, i.title, i.kind) for i in items if i.done}
        bfixture, cfixture = (fixture_for(h, fixture, courses, items) for h in (bhub, chub))
        print(f"hub.api: baseline {base['ref'] or 'this checkout'}, candidate {hub_ref or 'this checkout'}; "
              + ("shared fixture DB" if bfixture == cfixture else "own DB per side (schemas differ), same fixture rows"))
    print(f"mode: {'local (fixture hub.db via hub.api)' if local else 'sample'}; frozen clock {NOW.isoformat()}")
    bm, bv, bvis = render(base, local, bfixture, out, "baseline", args.keep_logs, bhub)
    cm, cv, cvis = render(cand, local, cfixture, out, "candidate", args.keep_logs, chub)
    rep = compare(bm, bv, cm, cv, hidden)
    rep.print("BEHAVIOUR (FAIL on any difference from the baseline)", ITEM_TABS + ["Courses", "Global"])
    visual(bvis, cvis).print("VISUAL (WARN only; never affects the exit code)")
    print(f"\nscreenshots: {out}")
    print("RESULT:", "FAIL" if rep.failed() else "PASS")
    sys.exit(1 if rep.failed() else 0)


if __name__ == "__main__":
    main()
