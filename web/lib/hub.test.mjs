import { test } from "node:test";
import assert from "node:assert/strict";
import { hideCourseItems, mergeItems, monthGrid, parsePreferredKinds, selectConnections, selectItemsDueOn, selectVisibleCourses, sortItems } from "./hub.js";

test("selectConnections: no data means nothing is connected", () => {
  const connections = selectConnections([], []);
  assert.deepEqual(
    connections.map((c) => c.connected),
    [false, false, false, false],
  );
});

test("selectConnections: source-tagged items mark that provider connected, others untouched", () => {
  const items = [
    { source: "canvas" },
    { source: "canvas" },
    { source: undefined }, // sample data - never counts toward a real connection
  ];
  const connections = selectConnections(items, []);
  const byId = Object.fromEntries(connections.map((c) => [c.id, c]));
  assert.equal(byId.canvas.connected, true);
  assert.equal(byId.canvas.detail, "2 items");
  assert.equal(byId.prairielearn.connected, false);
  assert.equal(byId.workday.connected, false);
});

test("selectConnections: imported Workday courses count as connected regardless of items", () => {
  const connections = selectConnections([], [{ code: "BMEG 201" }]);
  const workday = connections.find((c) => c.id === "workday");
  assert.equal(workday.connected, true);
  assert.equal(workday.detail, "1 course imported");
});

test("selectConnections: an unrecognized source shows up as its own custom PrairieLearn row", () => {
  // Any source that isn't one of the known providers is a PrairieLearn
  // instance a student pasted in directly (resolve_campus() accepts a full
  // URL for any self-hosted instance we don't have a fixed entry for).
  const items = [{ source: "pl.autoed.ok.ubc.ca" }, { source: "pl.autoed.ok.ubc.ca" }];
  const connections = selectConnections(items, []);
  const custom = connections.find((c) => c.id === "pl.autoed.ok.ubc.ca");
  assert.ok(custom, "custom source should get its own row");
  assert.equal(custom.connected, true);
  assert.equal(custom.detail, "2 items");
  // and it shouldn't duplicate or displace the known providers
  assert.equal(connections.filter((c) => c.id === "prairielearn").length, 1);
});

test("selectVisibleCourses: drops hidden courses, keeps everything else", () => {
  const courses = [{ code: "CPSC 121" }, { code: "OLD 100" }, { code: "MATH 100" }];
  assert.deepEqual(
    selectVisibleCourses(courses, ["OLD 100"]).map((c) => c.code),
    ["CPSC 121", "MATH 100"],
  );
  assert.deepEqual(selectVisibleCourses(courses, []).map((c) => c.code), ["CPSC 121", "OLD 100", "MATH 100"]);
});

test("hideCourseItems: drops items belonging to a hidden course", () => {
  const items = [{ course: "CPSC 121" }, { course: "OLD 100" }];
  assert.deepEqual(hideCourseItems(items, ["OLD 100"]).map((i) => i.course), ["CPSC 121"]);
});

test("mergeItems: keeps distinct (source, url) items and updates matching ones", () => {
  const base = [{ source: "canvas", url: "https://x/1", title: "Old title" }];
  const incoming = [
    { source: "canvas", url: "https://x/1", title: "New title" }, // same identity - replaces
    { source: "canvas", url: "https://x/2", title: "Different item" }, // new identity - added
  ];
  const merged = mergeItems(base, incoming);
  assert.equal(merged.length, 2);
  assert.equal(merged.find((i) => i.url === "https://x/1").title, "New title");
});

test("monthGrid: always 6 full weeks of 7 days, padded into neighbouring months", () => {
  const weeks = monthGrid(new Date(2026, 1, 1)); // February 2026
  assert.equal(weeks.length, 6);
  for (const week of weeks) assert.equal(week.length, 7);
  assert.equal(weeks[0][0].date.getMonth(), 0); // padded from January
  assert.ok(weeks.flat().some((cell) => cell.inMonth && cell.date.getDate() === 1));
});

test("selectItemsDueOn: only items due that calendar day, sorted, done items excluded by the caller", () => {
  const day = new Date(2026, 2, 15, 9, 0);
  const items = [
    { id: 1, due: new Date(2026, 2, 15, 23, 0).toISOString(), urgency: "low" },
    { id: 2, due: new Date(2026, 2, 15, 8, 0).toISOString(), urgency: "overdue" },
    { id: 3, due: new Date(2026, 2, 16, 8, 0).toISOString(), urgency: "overdue" },
  ];
  const due = selectItemsDueOn(items, day);
  assert.deepEqual(due.map((i) => i.id), [2, 1]); // overdue ranks before low, matches sortItems
});

test("parsePreferredKinds: empty/missing cookie value means nothing preferred", () => {
  assert.deepEqual(parsePreferredKinds(""), new Set());
  assert.deepEqual(parsePreferredKinds(undefined), new Set());
});

test("parsePreferredKinds: drops unknown ids so a stale/tampered cookie can't inject junk", () => {
  const kinds = parsePreferredKinds("exam,made-up,quiz");
  assert.deepEqual(kinds, new Set(["exam", "quiz"]));
});

test("sortItems: preferredKinds only re-orders within an urgency band, never across bands", () => {
  const items = [
    { id: 1, kind: "reading", urgency: "high", due: "2026-01-01T00:00:00Z" },
    { id: 2, kind: "quiz", urgency: "high", due: "2026-01-02T00:00:00Z" },
    { id: 3, kind: "exam", urgency: "critical", due: "2026-01-05T00:00:00Z" },
  ];
  const sorted = sortItems(items, new Set(["quiz"]));
  // critical still comes first even though it's not preferred - band beats preference.
  assert.equal(sorted[0].id, 3);
  // within the "high" band, the preferred quiz jumps ahead of the earlier-due reading.
  assert.equal(sorted[1].id, 2);
  assert.equal(sorted[2].id, 1);
});

test("sortItems: no preferredKinds argument behaves exactly as before (due-date order within a band)", () => {
  const items = [
    { id: 1, kind: "reading", urgency: "high", due: "2026-01-02T00:00:00Z" },
    { id: 2, kind: "quiz", urgency: "high", due: "2026-01-01T00:00:00Z" },
  ];
  const sorted = sortItems(items);
  assert.equal(sorted[0].id, 2);
  assert.equal(sorted[1].id, 1);
});
