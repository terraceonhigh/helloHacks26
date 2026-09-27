// Mirrors tests/test_workday.py exactly, against the same fixture, so the
// JS and Python parsers stay in step. Run with: node --test lib/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parseWorkdayCourses } from "./workday.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, "..", "..", "fixtures", "workday_view_my_courses.xlsx");

function load() {
  return parseWorkdayCourses(readFileSync(FIXTURE), "2026W1");
}

test("parses all course rows", () => {
  const courses = load();
  assert.deepEqual(
    courses.map((c) => c.code),
    ["FAKE 100", "FAKE 200", "FAKE 300"]
  );
});

test("fields from first row", () => {
  const [fake100] = load();
  assert.equal(fake100.term, "2026W1");
  assert.equal(fake100.title, "Introduction to Fake Studies");
  // Real Workday "Course Listing" text never embeds a section number (it
  // lives in a separate column this parser doesn't read) - always null.
  assert.equal(fake100.section, null);
});

test("duplicate component rows dedupe to one course", () => {
  // Real exports have one row per meeting component (Lecture, Lab,
  // Discussion...), each repeating the same Course Listing text.
  const codes = load().map((c) => c.code);
  assert.equal(codes.filter((c) => c === "FAKE 100").length, 1);
});

test("no separator falls back to raw listing as title", () => {
  const fake300 = load()[2];
  assert.equal(fake300.title, "fake300");
});
