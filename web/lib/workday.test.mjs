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
    ["CPSC 121", "MATH 200", "CPSC 210"]
  );
});

test("fields from first row", () => {
  const [cpsc121] = load();
  assert.equal(cpsc121.section, "001");
  assert.equal(cpsc121.term, "2026W1");
  assert.equal(cpsc121.title, "Models of Computation");
});

test("missing section still parses", () => {
  const cpsc210 = load()[2];
  assert.equal(cpsc210.section, null);
  assert.equal(cpsc210.title, "Software Construction");
});
