from hub.ics import parse

FEED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART:20260930T065900Z
SUMMARY:Quiz 2 [CPSC 121 101]
URL:https://canvas.ubc.ca/courses/7/assignments/99
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART:20261002T170000Z
SUMMARY:Office hours [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar_events/55
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART:20261005T000000Z
SUMMARY:Reading week
END:VEVENT
END:VCALENDAR
"""


def test_parse_assignment_and_event():
    items = parse(FEED, source="canvas")
    assert [i.kind for i in items] == ["assignment", "event", "assignment"]
    assert [i.category for i in items] == ["task", "deadline", "task"]
    assert items[0].course == "CPSC 121 101"
    assert items[0].title == "Quiz 2"
    assert items[0].due.day == 30


def test_no_course_suffix_is_fine():
    # Moodle feeds don't tag "[COURSE]" onto the summary.
    items = parse(FEED, source="moodle")
    assert items[2].course == ""
    assert items[2].title == "Reading week"
    assert items[2].source == "moodle"


# Real shape from a self-hosted Canvas: every event's URL is the generic
# course-calendar page, not a per-item link (#15/#47) - UID is what's unique.
CANVAS_UID_FEED = """\
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-99
DTSTART:20260930T065900Z
SUMMARY:Quiz 2 [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-55
DTSTART:20261002T170000Z
SUMMARY:Office hours [CPSC 121 101]
URL:https://canvas.ubc.ca/calendar?include_contexts=course_7
END:VEVENT
END:VCALENDAR
"""


def test_canvas_uid_gives_each_item_its_own_kind_and_deep_link():
    items = parse(CANVAS_UID_FEED, source="canvas", origin="https://canvas.ubc.ca")
    assert [i.kind for i in items] == ["assignment", "event"]
    # Same course-calendar URL on both raw events used to collide (source, url).
    assert items[0].url != items[1].url
    assert items[0].url == "https://canvas.ubc.ca/courses/7/assignments/99"
    assert items[1].url == "https://canvas.ubc.ca/calendar?event_id=55"
