import { test } from "node:test";
import assert from "node:assert/strict";
import { parsePreferredKinds, selectConnections, sortItems } from "./hub.js";

test("selectConnections: no data means nothing is connected", () => {
  const connections = selectConnections([], []);
  assert.deepEqual(
    connections.map((c) => c.connected),
    [false, false, false],
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
