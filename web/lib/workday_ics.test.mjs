import test from "node:test";
import assert from "node:assert/strict";
import { meetingsToIcs, parseReminders } from "./workday.js";

const lecture = {
  course: "CPSC 110", kind: "lecture", days: ["MO", "WE", "FR"], startTime: "10:00", endTime: "11:00",
  location: "Demo Hall, Room 110; Floor 1", termStart: "2026-09-08", termEnd: "2026-12-05", source: "workday",
};
const now = new Date("2026-09-27T12:00:00Z");

test("one weekly event per meeting, starting on the first class day on or after term start", () => {
  const ics = meetingsToIcs([lecture], { now });
  // 2026-09-08 is a Tuesday, so the first Mon/Wed/Fri class is Wednesday the 9th.
  assert.match(ics, /DTSTART;TZID=America\/Vancouver:20260909T100000\r\n/);
  assert.match(ics, /DTEND;TZID=America\/Vancouver:20260909T110000\r\n/);
  assert.match(ics, /RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261206T075959Z\r\n/);
  assert.match(ics, /SUMMARY:CPSC 110 lecture\r\n/);
  assert.equal(ics.match(/BEGIN:VEVENT/g).length, 1);
  assert.match(ics, /BEGIN:VTIMEZONE\r\nTZID:America\/Vancouver/);
  assert.ok(ics.endsWith("END:VCALENDAR\r\n"));
});

test("location text is escaped and reminders become alarms", () => {
  const ics = meetingsToIcs([lecture], { now, reminders: [10, 30] });
  assert.match(ics, /LOCATION:Demo Hall\\, Room 110\; Floor 1\r\n/);
  assert.match(ics, /TRIGGER:-PT10M/);
  assert.match(ics, /TRIGGER:-PT30M/);
  assert.equal(ics.match(/BEGIN:VALARM/g).length, 2);
});

test("no lines longer than 75 characters", () => {
  const long = { ...lecture, location: "A very long building name ".repeat(6) };
  for (const line of meetingsToIcs([long], { now }).split("\r\n")) assert.ok(line.length <= 75, line);
});

test("parseReminders keeps whole positive minutes only", () => {
  assert.deepEqual(parseReminders("10, 30"), [10, 30]);
  assert.deepEqual(parseReminders("10,10 abc -5 1.5"), [10]);
  assert.deepEqual(parseReminders(""), []);
});
