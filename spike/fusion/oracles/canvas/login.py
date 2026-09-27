"""Canvas "login": turn a browser-captured session into a requests.Session.

There is NO Canvas oracle server in this spike. Canvas has no published image,
and a source build doesn't fit the machine. So there's no fake fstudent to log in
as. This module exists so fusion/run.py has the same interface for every
provider. It builds a session from what a student's own browser already holds.
It never does a password or SSO login itself.

secrets.env (gitignored) keys, first match wins:
  CANVAS_COOKIE   the full Cookie header copied from a logged-in browser tab
                  (canvas_session=...; _csrf_token=...). This is the path the
                  adapter is written for: JSON comes back prefixed "while(1);".
  CANVAS_TOKEN    a personal access token (Authorization: Bearer). No prefix.

# ponytail: no automated capture. The student pastes a cookie. Upgrade path: a
# Playwright window where the student logs in through their school's SSO, then
# export its cookies to the requests.Session (keep them on the laptop only).
"""
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def read_secrets(path: Path = HERE / "secrets.env") -> dict:
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def login(base: str, secrets: dict) -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/json"
    if secrets.get("CANVAS_COOKIE"):
        s.headers["Cookie"] = secrets["CANVAS_COOKIE"]
    elif secrets.get("CANVAS_TOKEN"):
        s.headers["Authorization"] = f"Bearer {secrets['CANVAS_TOKEN']}"
    else:
        raise RuntimeError("canvas: no live server in this spike; set CANVAS_COOKIE or CANVAS_TOKEN "
                           "in oracles/canvas/secrets.env, or replay fixtures/snapshots/canvas.json")
    r = s.get(base.rstrip("/") + "/api/v1/users/self", timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError(f"canvas: session rejected ({r.status_code})")
    r.raise_for_status()
    return s
