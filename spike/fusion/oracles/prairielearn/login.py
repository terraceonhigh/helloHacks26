"""Log in to our self-hosted PrairieLearn as the fake student fstudent.

PrairieLearn has no username/password login of its own: in production the
student arrives through their school's SSO (SAML/Shibboleth/Google/Azure/LTI).
Our oracle runs PrairieLearn in *development mode*, whose /pl/login page has a
"dev_login" form that asserts a UID/name/UIN, the same identity an SSO
provider would assert. That is the local stand-in for SSO. The adapter never
sees any of this: it just gets an authenticated requests.Session.

# ponytail: dev-mode UID assertion, no password check. Anyone who can reach the
# port can be anyone, so up.sh binds it to 127.0.0.1 only. Upgrade path: run PL
# in production mode behind a SAML IdP (e.g. a SimpleSAMLphp container) and
# capture the session cookie from that flow instead.
"""
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


def dev_login(base: str, uid: str, name: str, uin: str | None = None, email: str | None = None) -> requests.Session:
    s = requests.Session()
    host = requests.utils.urlparse(base).hostname
    # Without this cookie, dev mode silently auto-logs every request in as the
    # dev administrator (config.authUid). We want the named user, not the admin.
    s.cookies.set("pl2_disable_auto_authn", "true", domain=host, path="/")
    base = base.rstrip("/")
    s.get(f"{base}/pl/login", timeout=30).raise_for_status()   # sets the session cookie
    r = s.post(f"{base}/pl/login", data={
        "__action": "dev_login", "__csrf_token": "",
        "uid": uid, "name": name, "uin": uin or "", "email": email or "",
    }, timeout=30, allow_redirects=False)
    if r.status_code not in (302, 303):
        raise RuntimeError(f"PrairieLearn dev_login failed: HTTP {r.status_code}")
    who = s.get(f"{base}/pl", timeout=30)
    who.raise_for_status()
    if name not in who.text:
        raise RuntimeError("PrairieLearn dev_login did not stick (user name not on /pl)")
    return s


def login(base: str, secrets: dict) -> requests.Session:
    """Session authenticated as the fake STUDENT fstudent."""
    return dev_login(base, secrets["FSTUDENT_UID"], secrets["FSTUDENT_NAME"],
                     secrets.get("FSTUDENT_UIN"), secrets.get("FSTUDENT_EMAIL"))
