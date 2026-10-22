"""Syllabus provider: extract the deadlines an LMS misses straight from a
syllabus a student pastes in (docs/design.md flow 4b) - a professor who never
put due dates on Canvas, or a PrairieLearn deadline buried at the bottom of a
PDF, both show up here instead of silently missing the dashboard.

Input is pasted text only for now (PDF extraction is future work per #17 -
`pypdf` is a new dependency, announce on the board first). Extraction is one
Claude API call with a JSON-schema structured output, so it returns exactly
the shape we need rather than a first "let's parse the model's prose" version
to work around (docs/design.md's structured-output guidance).

Model choice: claude-sonnet-5, not the more capable default - this is a
single bounded extraction call (find the deadlines in one document), not
open-ended reasoning, and it runs once per pasted syllabus rather than in an
agentic loop, so the cost difference is the one worth taking on a hackathon
budget. Bump to claude-opus-5 if real syllabi show it missing deadlines.

The API key (ANTHROPIC_API_KEY) goes in .env only - never commit it.

Try it:  uv run python -m hub.syllabus <path-to-syllabus.txt> "CPSC 121"
"""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from hub.models import Item, category_for

# Fixed offset like hub/prairielearn.py, not zoneinfo - the syllabus rarely
# states a timezone, so a specific date without one is assumed to mean this
# (#17: "timezone defaults to America/Vancouver and is flagged as assumed").
VANCOUVER = timezone(timedelta(hours=-7))

_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "short name of the graded item, e.g. 'Assignment 3' or 'Midterm exam'"},
                    "kind": {"type": "string", "description": "assignment, quiz, exam, reading, project, or the closest fit"},
                    "due": {"type": ["string", "null"], "description": "ISO 8601 date (YYYY-MM-DD) or datetime if the syllabus gives one; null if it only gives a relative reference like 'Week 5' with no resolvable date"},
                    "evidence": {"type": "string", "description": "the exact sentence or line this was found in, so a student can verify it"},
                },
                "required": ["title", "kind", "due", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

_PROMPT = """Extract every graded deadline (assignments, quizzes, exams, projects, readings with a due date) from this course syllabus.

Rules:
- Always return what you can find - never skip the whole document because one part is unclear.
- If a date is relative to the term ("Week 5 Friday", "the Monday after reading week") and you cannot resolve it to a real date from context in the syllabus itself, leave `due` null rather than guessing.
- `evidence` must be copied verbatim from the syllabus, not paraphrased.

Syllabus:

{text}"""


def _call_llm(text):
    """One structured-output call. Stubbed in tests (monkeypatch
    hub.syllabus._call_llm) - no network in tests (AGENTS.md rule 8). Imports
    `anthropic` here, not at module load, so importing hub.syllabus never
    requires ANTHROPIC_API_KEY to be set in an environment that only runs
    the stubbed tests."""
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
    )
    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)["items"]


def _parse_due(due_str):
    if not due_str:
        return None
    try:
        dt = datetime.fromisoformat(due_str)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VANCOUVER)
    return dt


def fetch(text, course_key):
    """Extract Items from pasted syllabus text for one course.

    Never fails on partial data (#17): an item with no resolvable date still
    comes back with due=None rather than being dropped, same as an undated
    Canvas assignment (hub/canvas.py's to_undated_item).

    `evidence` (the sentence a deadline was found in) is extracted but not
    yet stored - hub.models.Item has no field for it. Surfacing "found in
    syllabus, not in Canvas" and the supporting sentence is a shared-model
    change (rule 1) to propose separately, not to smuggle into this adapter.
    """
    items = []
    for raw in _call_llm(text):
        title = (raw.get("title") or "").strip()
        if not title:
            continue
        kind = raw.get("kind") or "assignment"
        items.append(Item(
            course=course_key,
            category=category_for(kind),
            kind=kind,
            title=title,
            due=_parse_due(raw.get("due")),
            # No real link, unlike every other adapter - a syllabus item's
            # url doubles as its (source, url) identity (rule 4), so give it
            # a stable synthetic one instead of "" (which would collide every
            # syllabus item in a course onto one row).
            url=f"syllabus:{course_key}#{quote(title)}",
            source="syllabus",
        ))
    return items


if __name__ == "__main__":
    import sys

    from hub import db
    from hub.models import Course

    path, course_key = sys.argv[1], sys.argv[2]
    with open(path) as f:
        items = fetch(f.read(), course_key)
    conn = db.connect()
    db.save(conn, [Course(code=course_key, section="", term="", title=course_key)], items)
    for i in items:
        print(f"{i.due:%a %b %d %H:%M}" if i.due else " " * 16, f"{i.kind:12} {i.title}")
