"""lauds: one CLI for every course deadline. Entry point: `lauds.cli:main`
(`pyproject.toml`'s `[project.scripts]`).

Every query command prints a human-readable table by default (fits 80
columns; dates shown in America/Vancouver) and, with `--json`, a stable
machine schema documented in `docs/cli.md`: for item rows, `lauds.compat`'s
main-field projection (minus `files`, which the row doesn't carry) plus
`id` and `status` (`lauds.models.status_of`, recomputed fresh every call,
never stored).
"""
import argparse
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from lauds import adapters, export_ics, paths, store
from lauds.adapters import fill_kwargs
from lauds.models import SOON_WINDOW, canonical_code
from lauds.sync import STALE_ERROR, SyncLocked, sync as run_sync

VAN = ZoneInfo("America/Vancouver")
WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


# --- small formatting helpers ------------------------------------------------

def _fit(value, width) -> str:
    s = "" if value is None else str(value)
    return s if len(s) <= width else (s[: max(0, width - 1)] + "…")


def _print_table(columns, rows):
    """columns: [(header, width, formatter(row) -> str)]. Kept to <=80 cols
    by construction: callers size their own widths."""
    if not rows:
        print("(nothing)")
        return
    print(" ".join(h.ljust(w) for h, w, _ in columns).rstrip())
    for row in rows:
        print(" ".join(_fit(f(row), w).ljust(w) for _, w, f in columns).rstrip())


def _local(due_iso) -> str:
    if not due_iso:
        return ""
    return datetime.fromisoformat(due_iso).astimezone(VAN).strftime("%Y-%m-%d %H:%M")


def _status(due_iso, done, now=None) -> str:
    """Same rule as lauds.models.status_of, from a query row's raw (due,
    done) instead of a rebuilt Item - see models.status_of for the rule
    itself; kept in sync via the shared SOON_WINDOW constant."""
    now = now or datetime.now(timezone.utc)
    if done:
        return "done"
    if due_iso is None:
        return "upcoming"
    due = datetime.fromisoformat(due_iso)
    if due < now:
        return "overdue"
    if due - now <= SOON_WINDOW:
        return "soon"
    return "upcoming"


def _item_row_dict(row) -> dict:
    """An upcoming()/undated()/by_course() row -> the documented JSON shape
    (docs/cli.md): compat's Item fields (minus `files`) + id + status."""
    code, category, kind, title, due, url, done, source, item_id = row
    return {
        "id": item_id,
        "course": code,
        "category": category,
        "kind": kind,
        "title": title,
        "due": due,
        "url": url,
        "source": source,
        "done": None if done is None else bool(done),
        "status": _status(due, done),
    }


def _emit(args, rows, columns, to_dict):
    if getattr(args, "json", False):
        print(json.dumps([to_dict(r) for r in rows], indent=2, sort_keys=True))
    else:
        _print_table(columns, rows)


ITEM_COLUMNS = (
    ("DUE", 16, lambda r: _local(r[4])),
    ("STATUS", 8, lambda r: _status(r[4], r[6])),
    ("COURSE", 10, lambda r: r[0]),
    ("KIND", 10, lambda r: r[2]),
    ("TITLE", 28, lambda r: r[3]),
    ("ID", 5, lambda r: r[8]),
)


# --- commands ----------------------------------------------------------------

def _parse_opts(pairs) -> dict:
    """`--opt base=https://x --opt course_code=math100` -> {"base": ...,
    "course_code": ...}. Same shape `lauds config set <source>.<key>
    <value>` writes, so an adapter's `login()`/`fetch()` can be driven by
    either one (BRIEF blocker finding: neither `login` nor `sync` used to
    be able to pass an adapter any argument at all)."""
    opts = {}
    for raw in pairs or ():
        key, sep, value = raw.partition("=")
        if not sep or not key:
            raise ValueError(f"--opt must be key=value, got {raw!r}")
        opts[key] = value
    return opts


def cmd_login(args) -> int:
    name = args.source
    try:
        mod = adapters.get(name)
    except KeyError as e:
        print(f"lauds login: {e}", file=sys.stderr)
        return 1
    login = getattr(mod, "login", None)
    if not callable(login):
        print(f"{name}: no login step needed (it isn't a session-based adapter)")
        return 0
    try:
        explicit = _parse_opts(args.opt)
    except ValueError as e:
        print(f"lauds login: {e}", file=sys.stderr)
        return 1
    cfg = {**paths.adapter_config(name), **explicit}
    kwargs, missing = fill_kwargs(login, cfg)
    if missing:
        print(f"lauds login {name}: needs " +
              ", ".join(f"--opt {m}=<value>" for m in missing), file=sys.stderr)
        return 1
    try:
        login(**kwargs)
    except Exception as e:  # noqa: BLE001 - report it, don't crash the CLI
        print(f"lauds login {name}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if explicit:
        paths.save_adapter_config(name, explicit)  # so a later `sync`/`login` doesn't need --opt again
    print(f"{name}: session saved")
    return 0


def cmd_sync(args) -> int:
    try:
        report = run_sync(args.sources or None, timeout=args.timeout)
    except SyncLocked as e:
        print(f"lauds sync: {e}", file=sys.stderr)
        return 3
    as_json = getattr(args, "json", False)
    for r in report.results:
        # With --json, stdout carries only the JSON array below (BRIEF minor
        # finding: these human lines used to print to stdout first, so
        # `lauds sync --json | python3 -c "json.load(sys.stdin)"` failed at
        # char 0) - still shown, just on stderr, so `--json` doesn't also
        # mean "silent".
        out = sys.stderr if as_json else sys.stdout
        if r.ok:
            n = ", ".join(f"{k} {v}" for k, v in sorted(r.counts.items())) if r.counts else "nothing"
            print(f"{r.source}: ok ({n})", file=out)
        else:
            tag = "re-login needed" if r.stale else "FAILED"
            print(f"{r.source}: {tag} - {r.error}", file=sys.stderr)
    if as_json:
        print(json.dumps([r.__dict__ for r in report.results], indent=2, sort_keys=True))
    return 1 if report.any_failed else 0


def cmd_status(args) -> int:
    conn = store.connect()
    rows = {s: (a, ls, ok, counts, err) for s, a, ls, ok, counts, err in store.sync_status(conn)}
    names = sorted(set(adapters.names()) | set(rows))
    out = []
    for name in names:
        if name in rows:
            attempt, success, ok, counts, err = rows[name]
            stale = bool(err) and err == STALE_ERROR
            out.append({"source": name, "last_attempt": attempt, "last_success": success,
                        "ok": ok, "counts": counts, "error": err, "stale": stale})
        else:
            out.append({"source": name, "last_attempt": None, "last_success": None,
                        "ok": None, "counts": None, "error": None, "stale": False})
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    cols = (("SOURCE", 12, lambda r: r["source"]),
            ("OK", 5, lambda r: {"True": "yes", "False": "no", "None": "never"}[str(r["ok"])]),
            ("LAST SUCCESS", 20, lambda r: _local(r["last_success"]) if r["last_success"] else ""),
            ("STALE", 6, lambda r: "yes" if r["stale"] else ""),
            ("ERROR", 24, lambda r: r["error"] or ""))
    _print_table(cols, out)
    return 0


def cmd_today(args) -> int:
    conn = store.connect()
    today = datetime.now(VAN).date()
    rows = [r for r in store.upcoming(conn) if r[4] and datetime.fromisoformat(r[4]).astimezone(VAN).date() == today]
    _emit(args, rows, ITEM_COLUMNS, _item_row_dict)
    return 0


def cmd_due(args) -> int:
    conn = store.connect()
    days = 7 if args.week else (args.days if args.days is not None else 14)
    cutoff = datetime.now(timezone.utc) + timedelta(days=days)
    course = canonical_code(args.course) if args.course else None
    rows = [r for r in store.upcoming(conn)
            if r[4] and datetime.fromisoformat(r[4]) <= cutoff and (course is None or r[0] == course)]
    _emit(args, rows, ITEM_COLUMNS, _item_row_dict)
    return 0


def cmd_undated(args) -> int:
    conn = store.connect()
    rows = store.undated(conn)
    if args.course:
        code = canonical_code(args.course)
        rows = [r for r in rows if r[0] == code]
    _emit(args, rows, ITEM_COLUMNS, _item_row_dict)
    return 0


def cmd_course(args) -> int:
    conn = store.connect()
    code = canonical_code(args.code)
    course_row = next((c for c in store.courses(conn) if c[0] == code), None)
    # BRIEF major finding: an undated item (a WeBWorK not-open/past-due set,
    # Canvas's own to_undated_item, ...) exists precisely so it doesn't "just
    # vanish" - by_course() alone (upcoming()'s grouping) never carried it.
    items = store.by_course(conn).get(code, []) + [r for r in store.undated(conn) if r[0] == code]
    textbooks = store.textbooks(conn, code)
    schedule = [s for s in store.schedule(conn) if s[0] == code]
    if args.json:
        print(json.dumps({
            "course": None if course_row is None else
                      {"code": course_row[0], "term": course_row[1], "title": course_row[2], "grade": course_row[3]},
            "items": [_item_row_dict(r) for r in items],
            "textbooks": [{"course": t[0], "title": t[1], "isbn": t[2], "required": bool(t[3]),
                           "price": t[4], "url": t[5]} for t in textbooks],
            "schedule": [{"course": s[0], "kind": s[1], "days": s[2].split(","), "start_time": s[3],
                          "end_time": s[4], "location": s[5], "term_start": s[6], "term_end": s[7],
                          "source": s[8]} for s in schedule],
        }, indent=2, sort_keys=True))
        return 0
    if course_row is None:
        print(f"(no course {code} - run `lauds sync` first, or check the code)")
    else:
        print(f"{course_row[0]}  {course_row[2]}  ({course_row[1]}, grade {course_row[3]})")
    _print_table(ITEM_COLUMNS, items)
    return 0


def cmd_show(args) -> int:
    conn = store.connect()
    item = store.get_item(conn, args.id)
    if item is None:
        print(f"lauds show: no item {args.id}", file=sys.stderr)
        return 1
    status = _status(item["due"], item["done"])
    if args.json:
        print(json.dumps({
            "id": item["id"], "course": item["course"], "category": item["category"], "kind": item["kind"],
            "title": item["title"], "due": item["due"], "url": item["url"], "source": item["source"],
            "done": item["done"], "status": status, "description": item["description"],
            "points": item["points"], "files": item["files"], "extra": item["extra"],
        }, indent=2, sort_keys=True))
        return 0
    print(f"[{item['id']}] {item['title']}  ({item['course'] or '(unknown course)'})")
    print(f"  {item['category']}/{item['kind']}  due {_local(item['due']) or '(none)'}  status={status}")
    if item["points"] is not None:
        print(f"  points: {item['points']}")
    print(f"  url: {item['url']}")
    for f in item["files"]:
        print(f"  file: {f['name']} ({f['kind']}) {f['url']}")
    if item["description"]:
        print(f"  description: {item['description']}")
    return 0


def cmd_schedule(args) -> int:
    conn = store.connect()
    rows = store.schedule(conn)
    if args.date:
        d = date.fromisoformat(args.date)
        wd = WEEKDAY_CODES[d.weekday()]
        rows = [r for r in rows if wd in r[2].split(",") and
                date.fromisoformat(r[6]) <= d <= date.fromisoformat(r[7])]
    if args.json:
        print(json.dumps([{"course": s[0], "kind": s[1], "days": s[2].split(","), "start_time": s[3],
                           "end_time": s[4], "location": s[5], "term_start": s[6], "term_end": s[7],
                           "source": s[8]} for s in rows], indent=2, sort_keys=True))
        return 0
    cols = (("COURSE", 10, lambda r: r[0]), ("KIND", 9, lambda r: r[1]), ("DAYS", 11, lambda r: r[2]),
            ("START", 6, lambda r: r[3][:5]), ("END", 6, lambda r: r[4][:5]), ("LOCATION", 16, lambda r: r[5]))
    _print_table(cols, rows)
    return 0


def cmd_textbooks(args) -> int:
    conn = store.connect()
    rows = store.textbooks(conn, args.course)
    if args.json:
        print(json.dumps([{"course": t[0], "title": t[1], "isbn": t[2], "required": bool(t[3]),
                           "price": t[4], "url": t[5]} for t in rows], indent=2, sort_keys=True))
        return 0
    cols = (("COURSE", 10, lambda r: r[0]), ("TITLE", 28, lambda r: r[1]),
            ("REQ", 4, lambda r: "yes" if r[3] else "no"),
            ("PRICE", 8, lambda r: "" if r[4] is None else f"${r[4]:.2f}"), ("ISBN", 14, lambda r: r[2]))
    _print_table(cols, rows)
    return 0


_SQL_LEADING = re.compile(r"\A(\s+|--[^\n]*\n|/\*.*?\*/)+", re.S)


def _validate_readonly_sql(query: str) -> None:
    body = _SQL_LEADING.sub("", query).strip()
    if not re.match(r"(?is)^(select|with)\b", body):
        raise ValueError("only SELECT/WITH queries are allowed")
    if ";" in body.rstrip().rstrip(";"):
        raise ValueError("only a single statement is allowed")


def cmd_sql(args) -> int:
    try:
        _validate_readonly_sql(args.query)
        conn = store.connect_readonly()
        cur = conn.execute(args.query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    except (ValueError, FileNotFoundError, sqlite3.Error) as e:
        print(f"lauds sql: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([dict(zip(cols, r)) for r in rows], indent=2, sort_keys=True, default=str))
        return 0
    if cols:
        print(" | ".join(cols))
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))
    return 0


def cmd_export_ics(args) -> int:
    from lauds.models import Item

    conn = store.connect()
    items = []
    for code, category, kind, title, due, url, done, source, item_id in store.upcoming(conn):
        items.append(Item(course=code, category=category, kind=kind, title=title,
                           due=datetime.fromisoformat(due), url=url, source=source,
                           done=None if done is None else bool(done)))
    ics = export_ics.to_ics(items, kind=args.kind)
    if args.out:
        Path(args.out).write_bytes(ics)
        print(f"wrote {args.out} ({len(ics)} bytes, {len(export_ics.known_kinds(items))} kinds)")
    else:
        sys.stdout.buffer.write(ics)
    return 0


_CONFIG_SEGMENT = r"[a-z][a-z0-9_-]*"  # allows e.g. "course_code", a real fetch() parameter name


def cmd_config_set(args) -> int:
    """`config set <key> <value>`. `<key>` is either a bare flat key (the
    original `config set canvas-feed-url <url>` shape) or `<source>.<key>`
    (BRIEF blocker fix: this is what `lauds.sync`/`lauds login --opt` read
    per adapter - `lauds config set webwork.base https://...`)."""
    dotted = re.match(rf"^({_CONFIG_SEGMENT})\.({_CONFIG_SEGMENT})$", args.key)
    if dotted:
        paths.save_adapter_config(dotted.group(1), {dotted.group(2): args.value})
    elif re.match(rf"^{_CONFIG_SEGMENT}$", args.key):
        path = paths.config_path()
        paths.ensure_dir(path.parent)
        data = paths.load_config()
        data[args.key] = args.value
        paths.secure_write_text(path, json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"lauds config set: bad key {args.key!r}", file=sys.stderr)
        return 1
    masked = args.value if len(args.value) <= 8 else args.value[:4] + "…" + args.value[-2:]
    print(f"{args.key} set ({masked})")
    return 0


# --- argument parsing --------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lauds", description="One CLI for every course deadline.")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("login", help="interactive login for one source")
    sp.add_argument("source")
    sp.add_argument("--opt", action="append", metavar="KEY=VALUE",
                     help="a config value this source's login/fetch needs (repeatable); "
                          "saved for later syncs too, same as `config set <source>.<key> <value>`")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("sync", help="fetch and save one or more sources (default: all)")
    sp.add_argument("sources", nargs="*")
    sp.add_argument("--timeout", type=float, default=60.0, help="per-source hard timeout, seconds")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("status", help="per-source last-sync status")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("today", help="items due today (America/Vancouver)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_today)

    sp = sub.add_parser("due", help="items due soon")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--week", action="store_true", help="due within 7 days (shorthand for --days 7)")
    g.add_argument("--days", type=int, help="due within N days (default 14)")
    sp.add_argument("--course", help="filter to one course code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_due)

    sp = sub.add_parser("undated", help="items with no due date (never shown by `due`/`today`)")
    sp.add_argument("--course", help="filter to one course code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_undated)

    sp = sub.add_parser("course", help="one course's items, textbooks and schedule")
    sp.add_argument("code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_course)

    sp = sub.add_parser("show", help="one item in full, incl. its url and files")
    sp.add_argument("id", type=int)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("schedule", help="recurring class meetings")
    sp.add_argument("--date", help="only meetings that occur on this date (YYYY-MM-DD)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_schedule)

    sp = sub.add_parser("textbooks", help="textbooks, required first")
    sp.add_argument("--course", help="filter to one course code")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_textbooks)

    sp = sub.add_parser("sql", help="read-only ad-hoc SQL (SELECT/WITH only)")
    sp.add_argument("query")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_sql)

    export = sub.add_parser("export", help="export commands")
    export_sub = export.add_subparsers(dest="export_command", required=True)
    sp = export_sub.add_parser("ics", help="write the merged .ics feed")
    sp.add_argument("--out", help="file to write (default: stdout)")
    sp.add_argument("--kind", help="only events of this kind (colour-coordination; see lauds.export_ics)")
    sp.set_defaults(func=cmd_export_ics)

    config = sub.add_parser("config", help="config commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    sp = config_sub.add_parser("set", help="set a config value (stored 0600, never echoed in full)")
    sp.add_argument("key")
    sp.add_argument("value")
    sp.set_defaults(func=cmd_config_set)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
