import { test } from "node:test";
import assert from "node:assert/strict";
import { parseIcs } from "./ics.js";

// Mirrors tests/test_ics.py's fixtures - this is a JS port of hub/ics.py,
// kept in sync deliberately (see ics.js's header comment).
const FEED = `BEGIN:VCALENDAR
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
`;

test("parseIcs: assignment and event kinds, course suffix stripped", () => {
  const items = parseIcs(FEED, "canvas");
  assert.deepEqual(items.map((i) => i.kind), ["assignment", "event", "assignment"]);
  assert.deepEqual(items.map((i) => i.category), ["task", "deadline", "task"]);
  assert.equal(items[0].course, "CPSC 121 101");
  assert.equal(items[0].title, "Quiz 2");
  assert.equal(items[0].due, "2026-09-30T06:59:00.000Z");
});

test("parseIcs: no course suffix is fine (Moodle-shaped feed)", () => {
  const items = parseIcs(FEED, "moodle");
  assert.equal(items[2].course, "");
  assert.equal(items[2].title, "Reading week");
  assert.equal(items[2].source, "moodle");
});

const CANVAS_UID_FEED = `BEGIN:VCALENDAR
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
`;

test("parseIcs: Canvas UID gives each item its own kind and deep link", () => {
  const items = parseIcs(CANVAS_UID_FEED, "canvas", "https://canvas.ubc.ca");
  assert.deepEqual(items.map((i) => i.kind), ["assignment", "event"]);
  // Same generic course-calendar URL on both raw events used to collide
  // on (source, url) - see hub/ics.py's UID fix.
  assert.notEqual(items[0].url, items[1].url);
  assert.equal(items[0].url, "https://canvas.ubc.ca/courses/7/assignments/99");
  assert.equal(items[1].url, "https://canvas.ubc.ca/calendar?event_id=55");
});
