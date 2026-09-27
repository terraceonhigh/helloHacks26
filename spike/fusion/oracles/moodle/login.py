"""Log in to our self-hosted Moodle as the fake student fstudent.

At a real school the student arrives through SSO and the adapter just gets the
browser's MoodleSession cookie. Here the stand-in is Moodle's own manual-auth
login form: GET /login/index.php for the logintoken, POST username/password.
The adapter never sees any of this.
"""
import re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent


def read_secrets(path: Path = HERE / "secrets.env") -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def password_login(base: str, username: str, password: str) -> requests.Session:
    base = base.rstrip("/")
    s = requests.Session()
    r = s.get(f"{base}/login/index.php", timeout=30)
    r.raise_for_status()
    m = re.search(r'name="logintoken" value="([^"]+)"', r.text)
    data = {"username": username, "password": password, "anchor": ""}
    if m:
        data["logintoken"] = m.group(1)
    r = s.post(f"{base}/login/index.php", data=data, timeout=30)
    r.raise_for_status()
    if "/login/index.php" in r.url or '"sesskey":"' not in r.text or "loginerrormessage" in r.text:
        raise RuntimeError(f"Moodle login failed for {username} (landed on {r.url})")
    return s


def login(base: str, secrets: dict) -> requests.Session:
    """Session authenticated as the fake STUDENT fstudent."""
    return password_login(base, secrets.get("FSTUDENT_USERNAME", "fstudent"), secrets["FSTUDENT_PASSWORD"])
