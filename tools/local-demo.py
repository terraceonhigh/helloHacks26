"""Local stand-in for Vercel: http://localhost:8080 serves /api/demo from
web/api/demo.py (the real full-semester demo) and proxies everything else to
`next start` on :3000. Run from a repo root on main: uv run python tools/local-demo.py
"""
import sys
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "web" / "api"))
import demo  # noqa: E402  web/api/demo.py (it puts the repo root on sys.path itself)

NEXT = "http://localhost:3000"


class Handler(demo.handler):
    def do_GET(self):
        if self.path.split("?")[0] == "/api/demo":
            return super().do_GET()
        # ponytail: GET-only proxy, enough for Sample mode; add methods if a demo needs POST
        try:
            with urllib.request.urlopen(NEXT + self.path) as r:
                body, status, ctype = r.read(), r.status, r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body, status, ctype = e.read(), e.code, e.headers.get("Content-Type", "")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


print("Lauds demo on http://localhost:8080 (Ctrl-C to stop)")
ThreadingHTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
