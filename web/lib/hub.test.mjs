import { test } from "node:test";
import assert from "node:assert/strict";
import { monthGrid, selectConnections, selectItemsDueOn } from "./hub.js";

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
