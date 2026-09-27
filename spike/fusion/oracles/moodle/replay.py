"""Record the raw HTTP the Moodle adapter does, and replay it without a network.

The oracle wraps a live session in RecordingSession and saves what the real
server returned into fixtures/moodle/. tests/test_moodle.py replays that
through ReplaySession, so the adapter parses exactly what the server sent.

Keys ignore the sesskey (it changes per login) and bodies are scrubbed of it.
"""
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

SESSKEY_PLACEHOLDER = "FXSESSKEY"


def request_key(method: str, url: str, params: dict | None = None, json_body=None) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k != "sesskey"]
    q += [(k, v) for k, v in (params or {}).items() if k != "sesskey"]
    if p.path.endswith("/lib/ajax/service.php") and json_body:
        calls = [{"methodname": c["methodname"], "args": c["args"]} for c in json_body]
        return "AJAX " + json.dumps(calls, sort_keys=True, separators=(",", ":"))
    return f"{method} {p.path}" + (("?" + urlencode(sorted(q))) if q else "")


def _slug(key: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_")
    return s[:120]


class RecordingSession:
    """Delegates to a real requests.Session and keeps every response body."""

    def __init__(self, inner):
        self.inner = inner
        self.records: dict[str, dict] = {}

    def _keep(self, key, r):
        self.records[key] = {"status": r.status_code, "content_type": r.headers.get("content-type", ""),
                             "url": r.url, "text": r.text}
        return r

    def get(self, url, params=None, **kw):
        return self._keep(request_key("GET", url, params), self.inner.get(url, params=params, **kw))

    def post(self, url, params=None, json=None, **kw):
        return self._keep(request_key("POST", url, params, json), self.inner.post(url, params=params, json=json, **kw))

    def save(self, directory: Path, sesskey: str | None):
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.iterdir():
            old.unlink()
        index = {}
        for i, (key, rec) in enumerate(sorted(self.records.items())):
            ext = "json" if "json" in rec["content_type"] else "html"
            name = f"{i:02d}_{_slug(key)}.{ext}"
            text = rec["text"]
            if sesskey:
                text = text.replace(sesskey, SESSKEY_PLACEHOLDER)
            (directory / name).write_text(text)
            url = rec["url"].replace(sesskey, SESSKEY_PLACEHOLDER) if sesskey else rec["url"]
            index[key] = {"file": name, "status": rec["status"], "content_type": rec["content_type"],
                          "url": url}
        (directory / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True))


class FakeResponse:
    def __init__(self, status, text, url, content_type=""):
        self.status_code, self.text, self.url = status, text, url
        self.headers = {"content-type": content_type}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


class ReplaySession:
    """Stands in for requests.Session: answers only requests that were recorded."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.index = json.loads((self.dir / "index.json").read_text())
        self.seen: list[str] = []

    def _answer(self, key):
        self.seen.append(key)
        if key not in self.index:
            raise KeyError(f"no fixture for {key}")
        rec = self.index[key]
        return FakeResponse(rec["status"], (self.dir / rec["file"]).read_text(), rec["url"], rec["content_type"])

    def get(self, url, params=None, **kw):
        return self._answer(request_key("GET", url, params))

    def post(self, url, params=None, json=None, **kw):
        return self._answer(request_key("POST", url, params, json))
