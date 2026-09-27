"""A fake requests.Session that serves fixtures/canvas/ by path (+ page= cursor). No network."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "canvas"


def pl_quiz1_url() -> str:
    first = (FIX / "README.md").read_text().splitlines()[0]
    return first.split("=", 1)[1].strip()


class FakeCanvas:
    def __init__(self, strip_prefix=False, overrides=None):
        idx = json.loads((FIX / "index.json").read_text())
        self.base = idx["base"]
        self.routes = {(r["path"], r["page"]): r for r in idx["responses"]}
        self.strip_prefix = strip_prefix
        self.overrides = overrides or {}       # (path, page) -> (body_text, headers)
        self.calls = []

    def get(self, url, params=None, headers=None, **kw):
        u = urlparse(url)
        assert f"{u.scheme}://{u.netloc}" == self.base, url
        page = (parse_qs(u.query).get("page") or [None])[0]
        self.calls.append((u.path, page, dict(params or {})))
        key = (u.path, page)
        r = requests.Response()
        r.url = url
        if key in self.overrides:
            text, hdrs = self.overrides[key]
        elif key in self.routes:
            route = self.routes[key]
            text, hdrs = (FIX / route["file"]).read_text(), route["headers"]
        else:
            r.status_code, r._content = 404, b'{"errors":[{"message":"The specified resource does not exist."}]}'
            return r
        if self.strip_prefix and text.startswith("while(1);"):
            text = text[len("while(1);"):]
        r.status_code = 200
        r._content = text.encode()
        r.encoding = "utf-8"
        r.headers.update(hdrs)
        return r
