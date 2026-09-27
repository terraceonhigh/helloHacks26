// Regression oracle for e3db118, mirrors tests/test_workday_truncated_dimension.py:
// the fixture declares <dimension ref="A1:A1"/> (so SheetJS's !ref is A1:A1)
// but has 8 populated rows; every course must still be parsed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { parseWorkdayCourses } from "./workday.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(here, "..", "..", "fixtures", "workday_truncated_dimension.xlsx");

function load() {
  return parseWorkdayCourses(readFileSync(FIXTURE), "2026W1");
}

test("truncated dimension still parses every row", () => {
  assert.deepEqual(
    load().map((c) => c.code),
    ["FAKE 101", "FAKE 202", "FAKE 303", "FAKE 404"]
  );
});

test("truncated dimension last row fields", () => {
  const courses = load();
  assert.equal(courses.at(-1).title, "Last Row Standing");
  assert.equal(courses.at(-1).term, "2026W1");
});
