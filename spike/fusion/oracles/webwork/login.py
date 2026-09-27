"""Log in to our self-hosted WeBWorK as the fake student fstudent.

Shared oracle interface: login(base, secrets) -> requests.Session.
Login is deliberately outside the adapter (at a real school it is SSO).

base is the WeBWorK *course* URL root, e.g. http://localhost:8081/webwork2/math100_2026w1
or the server root http://localhost:8081 (then the scenario course is assumed).
"""
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
COURSE = "math100_2026w1"


def read_secrets(path: Path = HERE / "secrets.env") -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def course_url(base: str) -> str:
    base = base.rstrip("/")
    if "/webwork2/" in base + "/":
        return base if base.split("/webwork2", 1)[1].strip("/") else f"{base}/{COURSE}"
    return f"{base}/webwork2/{COURSE}"


def login(base: str, secrets: dict, user: str = "fstudent") -> requests.Session:
    """Password login (2FA is off for the fake course). Raises on failure."""
    url = course_url(base)
    key = "FSTUDENT_PASSWORD" if user == "fstudent" else f"{user.upper()}_PASSWORD"
    s = requests.Session()
    r = s.post(f"{url}/", data={"user": user, "passwd": secrets[key]}, timeout=30)
    r.raise_for_status()
    # A failed login re-renders the form; a good one sets the course session cookie
    # and shows the set list.
    if 'id="login_form"' in r.text or not any(c.name.startswith("WeBWorK") for c in s.cookies):
        raise RuntimeError(f"WeBWorK login failed for {user} at {url}")
    return s


if __name__ == "__main__":
    import sys
    b = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8081"
    sess = login(b, read_secrets())
    print("logged in; cookies:", [c.name for c in sess.cookies])
