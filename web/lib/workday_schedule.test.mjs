// Mirrors tests/test_workday_schedule.py, against the same fixture, so the
// JS and Python parsers stay in step. Run with: node --test lib/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as XLSX from "xlsx";
import { parseWorkdaySchedule } from "./workday.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, "..", "..", "fixtures", "workday_view_my_courses.xlsx");

function load() {
  return parseWorkdaySchedule(readFileSync(FIXTURE), "2026W1");
}

function oneRowWorkbook(rows) {
  const sheet = XLSX.utils.aoa_to_sheet(rows);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "View My Courses");
  return XLSX.write(workbook, { type: "array", bookType: "xlsx" });
}

test("one meeting per component row", () => {
  const meetings = load();
  assert.deepEqual(meetings.map((m) => [m.course, m.kind]), [
    ["BMEG 000", "lecture"],
    ["BMEG 000", "lab"],
    ["BMEG 001", "lecture"],
    ["BMEG 002", "lecture"],
  ]);
});

test("fields from first row", () => {
  const [m] = load();
  assert.equal(m.days.join(","), "MO,WE,FR");
  assert.equal(m.startTime, "10:00");
  assert.equal(m.endTime, "11:00");
  assert.equal(m.termStart, "2026-09-08");
  assert.equal(m.termEnd, "2026-12-05");
  assert.equal(m.location, "Fake Building (FAKE), Floor: 1, Room: 100");
  assert.equal(m.source, "workday");
});

test("kind for every known instructional format", () => {
  const cases = [
    ["Lecture", "lecture"], ["Laboratory", "lab"], ["Seminar", "seminar"],
    ["Tutorial", "tutorial"], ["Discussion", "tutorial"], ["Exam", "exam"],
    ["Something Unseen", "class"],
  ];
  for (const [formatText, expected] of cases) {
    const buf = oneRowWorkbook([
      ["Course Listing", "Instructional Format", "Meeting Patterns"],
      ["BMEG 000 - Fake Thermodynamics", formatText, "2026-09-08 - 2026-12-05 | Mon Wed Fri | 10:00 a.m. - 11:00 a.m. | Room 1"],
    ]);
    assert.equal(parseWorkdaySchedule(buf, "2026W1")[0].kind, expected);
  }
});

test("a line with no recognizable days is skipped, not guessed", () => {
  const buf = oneRowWorkbook([
    ["Course Listing", "Instructional Format", "Meeting Patterns"],
    ["BMEG 000 - Fake Thermodynamics", "Lecture", "2026-09-08 - 2026-12-05 | TBD | 10:00 a.m. - 11:00 a.m. | Room 1"],
  ]);
  assert.deepEqual(parseWorkdaySchedule(buf, "2026W1"), []);
});

test("an unparseable time is skipped, not guessed", () => {
  const buf = oneRowWorkbook([
    ["Course Listing", "Instructional Format", "Meeting Patterns"],
    ["BMEG 000 - Fake Thermodynamics", "Lecture", "2026-09-08 - 2026-12-05 | Mon Wed Fri | TBD | Room 1"],
  ]);
  assert.deepEqual(parseWorkdaySchedule(buf, "2026W1"), []);
});

test("a bare dash meeting pattern produces no meetings", () => {
  const buf = oneRowWorkbook([
    ["Course Listing", "Instructional Format", "Meeting Patterns"],
    ["BMEG 000 - Fake Thermodynamics", "Lecture", "-"],
  ]);
  assert.deepEqual(parseWorkdaySchedule(buf, "2026W1"), []);
});

test("multiple meeting lines in one cell all parse", () => {
  const pattern = [
    "2026-09-08 - 2026-12-05 | Mon Wed | 10:00 a.m. - 11:00 a.m. | Room 1",
    "2026-09-08 - 2026-12-05 | Fri | 09:00 a.m. - 10:00 a.m. | Room 2",
  ].join("\n");
  const buf = oneRowWorkbook([
    ["Course Listing", "Instructional Format", "Meeting Patterns"],
    ["BMEG 000 - Fake Thermodynamics", "Lecture", pattern],
  ]);
  const meetings = parseWorkdaySchedule(buf, "2026W1");
  assert.equal(meetings.length, 2);
  assert.deepEqual(meetings[0].days, ["MO", "WE"]);
  assert.deepEqual(meetings[1].days, ["FR"]);
  assert.equal(meetings[1].location, "Room 2");
});

test("an export with no Meeting Patterns column returns no meetings", () => {
  const buf = oneRowWorkbook([
    ["Course Listing", "Section"],
    ["BMEG 000 - Fake Thermodynamics", "101"],
  ]);
  assert.deepEqual(parseWorkdaySchedule(buf, "2026W1"), []);
});
