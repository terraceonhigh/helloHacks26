"""Local sync: log into every adapter this laptop supports (Canvas,
PrairieLearn - real browser logins via hub.site), then push everything to a
hosted dashboard with a sync key. Same trust model as the browser extension
(paste-a-key sync, hub/hosted.py): the key is generated here, the server
only ever sees sha256(key). This file plus hub/site.py, hub/models.py,
hub/canvas.py and hub/prairielearn.py is the whole dependency - see
tools/sync.sh for a one-line downloader that doesn't need the full repo.
"""
import argparse
import base64
import secrets
import sys
from pathlib import Path

import requests

from hub import canvas, prairielearn

KEY_PATH = Path.home() / ".ubc-hub" / "sync_key"

# Providers that log the student in themselves and need no per-school base
# URL - the "just works" set this tool scans by default. Moodle/Blackboard/
# Brightspace need a school's own base URL to even try, so they're a
# deliberately separate, opt-in path (not built here yet) rather than
# something this default scan can guess at.
PROVIDERS = {"canvas": canvas.fetch, "prairielearn": prairielearn.fetch}


def load_or_create_key():
    if KEY_PATH.exists():
        return KEY_PATH.read_text().strip()
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    KEY_PATH.parent.mkdir(mode=0o700, exist_ok=True)
    KEY_PATH.write_text(key)
    KEY_PATH.chmod(0o600)
    return key


def _item_row(item):
    return {"course": item.course, "category": item.category, "kind": item.kind,
            "title": item.title, "due": item.due.isoformat() if item.due else None,
            "url": item.url, "source": item.source, "done": item.done}


def _course_row(course):
    return {"code": course.code, "section": course.section, "term": course.term,
            "title": course.title, "grade": course.grade}


def push(hosted_base, key, source, courses, items):
    res = requests.post(
        f"{hosted_base.rstrip('/')}/api/sync",
        headers={"Authorization": f"Bearer {key}"},
        json={"source": source, "courses": [_course_row(c) for c in courses],
              "items": [_item_row(i) for i in items]},
        timeout=30,
    )
    res.raise_for_status()
    return res.json().get("items", 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosted-base", default="https://hello-hacks26-one.vercel.app",
                         help="the hosted dashboard to sync into")
    parser.add_argument("--only", nargs="+", choices=sorted(PROVIDERS),
                         help="scan only these providers (default: all of them)")
    args = parser.parse_args(argv)

    key = load_or_create_key()
    total = 0
    for name in args.only or sorted(PROVIDERS):
        print(f"--- {name}: opening a browser window, log in yourself ---")
        try:
            courses, items = PROVIDERS[name]()
        except Exception as exc:
            print(f"{name}: skipped ({exc})", file=sys.stderr)
            continue
        stored = push(args.hosted_base, key, name, courses, items)
        total += stored
        print(f"{name}: synced {stored} items")

    print(f"\nSynced {total} items. Paste this sync key into the website's "
          f"Settings > Connections:\n{key}")


if __name__ == "__main__":
    raise SystemExit(main())
