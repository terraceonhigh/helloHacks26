// Mirrors tests/test_workday.py exactly, against the same fixture, so the
// JS and Python parsers stay in step. Run with: node --test lib/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { courseFromListing, parseWorkdayCourses } from "./workday.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, "..", "..", "fixtures", "workday_view_my_courses.xlsx");

const EXPECTED_CODES = [
  "BMEG 210", "BMEG 245", "APSC 160", "MECH 260", "BMEG 257",
  "BMEG 201", "ANTH 100", "AMNE 151", "BMEG 230",
];

function load() {
  return parseWorkdayCourses(readFileSync(FIXTURE), "2026W1");
}

test("parses all unique course rows", () => {
  assert.deepEqual(load().map((c) => c.code), EXPECTED_CODES);
});

test("fields from first row", () => {
  const [bmeg210] = load();
  assert.equal(bmeg210.term, "2026W1");
  assert.equal(bmeg210.title, "Thermodynamics in Biomedical Engineering");
  // Real Workday "Course Listing" text never embeds a section number (it
  // lives in a separate column this parser doesn't read) - always null.
  assert.equal(bmeg210.section, null);
});

test("duplicate component rows dedupe to one course", () => {
  // Real exports have one row per meeting component (Lecture, Lab,
  // Discussion...), each repeating the same Course Listing text. BMEG 210
  // has 2 rows (Lecture + Discussion) and BMEG 230 has 3 in this export.
  const codes = load().map((c) => c.code);
  assert.equal(codes.filter((c) => c === "BMEG 210").length, 1);
  assert.equal(codes.filter((c) => c === "BMEG 230").length, 1);
});

test("no separator falls back to raw listing as title", () => {
  // Doesn't occur in the real export (every real listing has " - "), so
  // this exercises the fallback directly rather than via a fixture.
  const course = courseFromListing("FOO101", "2026W1");
  assert.equal(course.code, "FOO 101");
  assert.equal(course.title, "FOO101");
});
