import { test } from "node:test";
import assert from "node:assert/strict";
import { fetchDemo, fetchDemoMeetings, fetchUpcoming, fetchCourses, resetDemoCache } from "./hub.js";

const demoBody = {
  demo: true,
  items: [{ course: "CPSC 110", category: "task", kind: "assignment", title: "Problem Set 4", due: "2026-09-29T06:59:00+00:00", url: "https://canvas.ubc.ca/courses/1001/assignments/5001", source: "canvas", done: false, status: "soon", urgency: "medium" }],
  announcements: [],
  courses: [{ code: "CPSC 110", term: "2026W1", title: "Intro to Program Design (Demo)", grade: 86.4 }],
  schedule: [{ course: "CPSC 110", kind: "lab", days: ["MO"], start_time: "14:00", end_time: "16:00", location: "Demo Computing Lab", term_start: "2026-08-25", term_end: "2026-11-20", source: "workday" }],
};

test("fetchDemo: uses /api/demo rows when it answers", async () => {
  resetDemoCache();
  const demo = await fetchDemo(async (url) => {
    assert.equal(url, "/api/demo");
    return { ok: true, json: async () => demoBody };
  });
  assert.equal(demo.items[0].source, "canvas");
  assert.equal(demo.items[0].title, "Problem Set 4");
  assert.equal(demo.courses[0].grade, 86.4);
});

test("fetchDemo: a failing or non-200 /api/demo resolves to null, never throws", async () => {
  resetDemoCache();
  assert.equal(await fetchDemo(async () => { throw new Error("offline"); }), null);
  resetDemoCache();
  assert.equal(await fetchDemo(async () => ({ ok: false, status: 500 })), null);
  resetDemoCache();
  assert.equal(await fetchDemo(async () => ({ ok: true, json: async () => ({ nope: 1 }) })), null);
});

test("fetchUpcoming/fetchCourses (hosted Sample mode): fall back to built-in sample rows when /api/demo fails", async () => {
  resetDemoCache();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const items = await fetchUpcoming(true);
    assert.ok(items.length > 0);
    assert.ok(items.every((i) => i.source === undefined)); // the hardcoded SAMPLE_ROWS
    const courses = await fetchCourses(true);
    assert.ok(courses.length > 0);
  } finally {
    globalThis.fetch = realFetch;
    resetDemoCache();
  }
});

test("fetchDemoMeetings: /api/demo's schedule rows in the Workday-import shape, Sample mode only", async () => {
  resetDemoCache();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, json: async () => demoBody });
  try {
    assert.deepEqual(await fetchDemoMeetings(true), [{
      course: "CPSC 110", kind: "lab", days: ["MO"], startTime: "14:00", endTime: "16:00",
      location: "Demo Computing Lab", termStart: "2026-08-25", termEnd: "2026-11-20", source: "workday",
    }]);
    assert.deepEqual(await fetchDemoMeetings(false), []); // Sample off: nothing fake
  } finally {
    globalThis.fetch = realFetch;
    resetDemoCache();
  }
});
