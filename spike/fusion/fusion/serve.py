"""Headless JSON server over the fused tracks. Stdlib http.server, 127.0.0.1 only.

    python -m fusion.serve --snapshots DIR [--port N]
    python -m fusion.serve --live oracles/sources.toml [--port N]

GET /tracks[?all=1&course=CPSC%20121]   the fused list (status computed per request)
GET /tracks/<id>                        one track: observations, evidence, conflicts, provenance
GET /courses                            resolved courses with per-source labels
GET /observations                       raw, unfused
GET /health                             per source ok/error, counts, fetched_at
"""
from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

from fusion import fuse as F
from fusion import run
from fusion.model import Track


@dataclass
class State:
    results: list[run.SourceResult]
    courses: list[F.FusedCourse] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    course_of: dict = field(default_factory=dict)       # (source, course_source_id) -> key
    fuse_error: str | None = None


def build_state(results: list[run.SourceResult]) -> State:
    st = State(results)
    snaps = run.snapshots(results)
    try:
        st.courses, st.tracks, st.warnings = F.fuse(snaps)
        st.course_of, _, _ = F.resolve_courses(snaps)
    except Exception as e:  # noqa: BLE001 - serve /health with the reason rather than die
        st.fuse_error = f"{type(e).__name__}: {e}"
    return st


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def make_handler(state: State, now: Callable[[], datetime] = _now):
    # ponytail: state is fetched once at startup; a live refresh needs a POST /refresh or a
    # background re-collect swapping `state` atomically.
    class Handler(BaseHTTPRequestHandler):
        server_version = "fusion-spike/0"

        def log_message(self, fmt, *args):   # quiet; nothing secret is in URLs anyway
            pass

        def _send(self, code: int, body):
            data = json.dumps(body, indent=2, sort_keys=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            u = urlsplit(self.path)
            path = u.path.rstrip("/") or "/"
            q = parse_qs(u.query)
            t = now()
            try:
                if path == "/tracks":
                    return self._tracks(q, t)
                if path.startswith("/tracks/"):
                    tid = unquote(path[len("/tracks/"):])
                    tr = next((x for x in state.tracks if x.id == tid), None)
                    if tr is None:
                        return self._send(404, {"error": f"no track {tid!r}"})
                    body = F.track_json(tr, t, full=True)
                    body["course_labels"] = next((c.labels for c in state.courses if c.key == tr.course), [])
                    return self._send(200, body)
                if path == "/courses":
                    return self._send(200, {"courses": [F.course_json(c) for c in state.courses]})
                if path == "/observations":
                    obs = [F.observation_json(o, state.course_of.get((o.source, o.course_source_id),
                                                                     f"{o.source}:{o.course_source_id}"))
                           for s in run.snapshots(state.results) for o in s.items]
                    return self._send(200, {"count": len(obs), "observations": obs})
                if path == "/health":
                    return self._send(200, {"ok": all(r.error is None for r in state.results) and not state.fuse_error,
                                            "now": t.isoformat(), "sources": run.health(state.results),
                                            "fuse_error": state.fuse_error, "warnings": state.warnings})
                if path == "/":
                    return self._send(200, {"endpoints": ["/tracks", "/tracks/<id>", "/courses",
                                                          "/observations", "/health"]})
                return self._send(404, {"error": f"no route {u.path!r}"})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _tracks(self, q, t):
            include_done = (q.get("all") or ["0"])[0].lower() in ("1", "true", "yes")
            course = (q.get("course") or [None])[0]
            ts = state.tracks
            if course:
                ts = [x for x in ts if F.course_matches(x.course, course)]
            ts = F.order(ts, t, include_done=include_done)
            return self._send(200, {"now": t.isoformat(), "count": len(ts),
                                    "tracks": [F.track_json(x, t) for x in ts]})

    return Handler


def make_server(state: State, port: int = 0, now: Callable[[], datetime] = _now) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, now))


def serve_in_thread(state: State, port: int = 0, now: Callable[[], datetime] = _now):
    srv = make_server(state, port, now)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, th


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m fusion.serve")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshots", metavar="DIR")
    g.add_argument("--live", metavar="TOML")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    results = run.collect({"snapshots": a.snapshots} if a.snapshots else {"live": a.live})
    state = build_state(results)
    srv = make_server(state, a.port)
    for h in run.health(results):
        print(f"{h['source']:>14}: {'ok' if h['ok'] else 'ERROR ' + str(h['error'])}  "
              f"{h['observations']} observations")
    print(f"{len(state.tracks)} tracks, {len(state.warnings)} warnings; "
          f"serving http://127.0.0.1:{srv.server_address[1]}/tracks")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
