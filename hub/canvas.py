"""Canvas adapter without API tokens.

The student logs in to canvas.ubc.ca themselves (CWL + Duo) in a real browser
window (hub.site handles that part). We reuse that session to call the same
/api/v1 JSON endpoints Canvas's own web pages use. We never see or store the
CWL password.

Try it:  uv run python -m hub.canvas
"""
import json
from datetime import date, datetime, timedelta

from hub import site
from hub.models import Course, Item, category_for

BASE = "https://canvas.ubc.ca"
SITE = "canvas"
# Canvas's plannable_type -> our kind. Unlisted types (assignment, discussion_topic,
# wiki_page, ...) default to "assignment": still a task, just not one we've named yet.
KINDS = {"announcement": "announcement", "calendar_event": "event", "quiz": "quiz"}


def unwrap(text):
    # Canvas prefixes cookie-authenticated JSON with while(1); to block JSON hijacking.
    return json.loads(text.removeprefix("while(1);"))


def to_course(c):
    enr = next(iter(c.get("enrollments") or []), {})
    return Course(
        code=c.get("course_code", ""),
        section="",  # ponytail: Canvas codes aren't consistent enough to split; match on Workday's side
        term=(c.get("term") or {}).get("name", ""),
        title=c.get("name", ""),
        grade=enr.get("computed_current_score"),
    )


def done_from_submissions(p):
    # Verified against a real planner/items response: "submissions" is a dict
    # (submitted/excused/graded/...) for anything gradeable, or a bare `false`
    # for announcements/events - nothing to report there, so None not False.
    submissions = p.get("submissions")
    if not isinstance(submissions, dict):
        return None
    return bool(submissions.get("submitted") or submissions.get("excused"))


def to_item(p, course_codes):
    due = p.get("plannable_date")
    kind = KINDS.get(p.get("plannable_type"), "assignment")
    return Item(
        course=course_codes.get(p.get("course_id"), p.get("context_name", "")),
        category=category_for(kind),
        kind=kind,
        title=(p.get("plannable") or {}).get("title", ""),
        due=datetime.fromisoformat(due) if due else None,
        url=BASE + p.get("html_url", ""),
        source="canvas",
        done=done_from_submissions(p),
    )


def login():
    """Open a visible browser; the student signs in; we save the session."""
    site.login(SITE, BASE)


def fetch(start=None, end=None):
    """Return (courses, items) for start..end. Logs in if needed.

    Default is a whole UBC term either side of today (~4 months), not just
    the coming week: planner/items needs *some* range, and Canvas doesn't
    hand back "the whole term" for us to use instead.
    """
    start = start or date.today() - timedelta(days=120)
    end = end or date.today() + timedelta(days=120)
    return site.fetch_with_session(SITE, BASE, lambda req: _run(req, start, end))


def _run(req, start, end):
    raw = site.get_all(req, f"{BASE}/api/v1/courses", {
        "include[]": ["total_scores", "term"], "enrollment_state": "active", "per_page": 100}, unwrap)
    courses = [to_course(c) for c in raw]
    codes = {c["id"]: c.get("course_code", "") for c in raw}
    plan = site.get_all(req, f"{BASE}/api/v1/planner/items", {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "per_page": 100}, unwrap)
    return courses, [to_item(p, codes) for p in plan]


if __name__ == "__main__":
    from hub import db

    courses, items = fetch()
    db.save(db.connect(), courses, items)  # persist so hub.db.upcoming() etc. can query it later
    for c in courses:
        print(f"{c.code:30} {c.grade if c.grade is not None else '-':>6}  {c.title}")
    print()
    for i in sorted(items, key=lambda i: (i.due is None, i.due or 0)):
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.category:9} {i.kind:12} {i.course:20} {i.title}")
