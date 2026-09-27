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

test("parses all unique course rows", () => {
  assert.deepEqual(load().map((c) => c.code), ["BMEG 000", "BMEG 001", "BMEG 002"]);
});

test("fields from first row", () => {
  const [bmeg000] = load();
  assert.equal(bmeg000.term, "2026W1");
  assert.equal(bmeg000.title, "Fake Thermodynamics");
  assert.equal(bmeg000.section, null);
});

test("duplicate component rows dedupe to one course", () => {
  const codes = load().map((c) => c.code);
  assert.equal(codes.filter((c) => c === "BMEG 000").length, 1);
});

test("no separator falls back to raw listing as title", () => {
  const bmeg002 = load()[2];
  assert.equal(bmeg002.title, "bmeg002");
});
