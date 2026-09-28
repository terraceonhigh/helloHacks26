import { test } from "node:test";
import assert from "node:assert/strict";
import { hideCourseItems, isDone, itemKey, mergeItems, mergeMeetings, monthGrid, parsePreferredKinds, selectActiveItems, selectConnections, selectCurrentTermMeetings, selectDaySchedule, selectItemsDueOn, selectMeetingsOn, selectVisibleCourses, sortItems, syncKeyFromHash } from "./hub.js";

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

test("selectConnections: WeBWorK items never get swept into the custom-PrairieLearn-instance bucket", () => {
  // Verified live: a real account's WeBWorK items all had due=None (every
  // set was closed or not-yet-open - hub/webwork.py's own module docstring
  // says a due date only exists for a currently-open set), so /api/upcoming
  // never returns them and this can't be tracked by item count like
  // Canvas/PrairieLearn - it's tracked in page.js off the connect response
  // instead. What still matters here: "webwork" must not fall through to
  // the "any other source is a pasted PrairieLearn instance" fallback.
  const items = [{ source: "webwork" }, { source: "webwork" }, { source: "webwork" }];
  const connections = selectConnections(items, []);
  assert.equal(connections.find((c) => c.id === "webwork"), undefined);
  assert.equal(connections.find((c) => c.label?.includes("webwork")), undefined);
});

test("selectConnections: loaded Workday meetings count as connected regardless of items", () => {
  // Workday feeds the Schedule tab only, never the course list (no
  // assignment data ever comes from it) - "connected" tracks meetings, not
  // courses.
  const meetings = [{ course: "BMEG 201", kind: "lecture", days: ["MO"], startTime: "10:00" }];
  const connections = selectConnections([], meetings);
  const workday = connections.find((c) => c.id === "workday");
  assert.equal(workday.connected, true);
  assert.equal(workday.detail, "1 class meeting");
});

test("selectConnections: an unrecognized source shows up as its own custom PrairieLearn row", () => {
  // Any source that isn't one of the known providers is a PrairieLearn
  // instance a student pasted in directly (resolve_campus() accepts a full
  // URL for any self-hosted instance we don't have a fixed entry for). The
  // source is "pl-<host>", not the bare host (PM review on #56: a bare host
  // could collide with another provider's own key) - the id keeps that
  // prefix (it's still the real (source, url) identity), but the label
  // strips it back off for display.
  const items = [{ source: "pl-pl.autoed.ok.ubc.ca" }, { source: "pl-pl.autoed.ok.ubc.ca" }];
  const connections = selectConnections(items, []);
  const custom = connections.find((c) => c.id === "pl-pl.autoed.ok.ubc.ca");
  assert.ok(custom, "custom source should get its own row");
  assert.equal(custom.connected, true);
  assert.equal(custom.detail, "2 items");
  assert.equal(custom.label, "PrairieLearn (pl.autoed.ok.ubc.ca)");
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

test("itemKey: matches mergeItems' own identity, so a manual check-off keys off the same thing", () => {
  const item = { source: "canvas", url: "https://x/1" };
  assert.equal(itemKey(item), "canvas https://x/1");
});

test("isDone: a manual check-off is done regardless of the backend's own status/done", () => {
  const item = { source: "canvas", url: "https://x/1", status: "overdue", done: false };
  assert.equal(isDone(item), false); // unaffected without a manual override
  assert.equal(isDone(item, [itemKey(item)]), true); // student crossed it off themselves
});

test("isDone: falls back to status, then the raw done flag, same as before manual check-off existed", () => {
  assert.equal(isDone({ source: "s", url: "u", status: "done" }), true);
  assert.equal(isDone({ source: "s", url: "u", status: "overdue" }), false);
  assert.equal(isDone({ source: "s", url: "u", done: true }), true);
  assert.equal(isDone({ source: "s", url: "u", done: false }), false);
});

test("selectActiveItems: a manually checked-off item disappears like any other done item", () => {
  const items = [
    { source: "canvas", url: "https://x/1", title: "Keep" },
    { source: "canvas", url: "https://x/2", title: "Checked off" },
  ];
  const active = selectActiveItems(items, ["canvas https://x/2"]);
  assert.deepEqual(active.map((i) => i.title), ["Keep"]);
});

test("mergeMeetings: keeps distinct weekly slots and updates matching ones", () => {
  const base = [{ course: "CPSC 121", kind: "lecture", days: ["MO", "WE"], startTime: "10:00", location: "Old room" }];
  const incoming = [
    { course: "CPSC 121", kind: "lecture", days: ["MO", "WE"], startTime: "10:00", location: "New room" }, // same slot - replaces
    { course: "CPSC 121", kind: "lab", days: ["FR"], startTime: "09:00", location: "Lab room" }, // different kind - added
  ];
  const merged = mergeMeetings(base, incoming);
  assert.equal(merged.length, 2);
  assert.equal(merged.find((m) => m.kind === "lecture").location, "New room");
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

test("selectMeetingsOn: matches a Meeting's weekday, sorted by start time, within its term", () => {
  const meetings = [
    { course: "CPSC 121", kind: "lecture", days: ["MO", "WE", "FR"], startTime: "10:00", endTime: "11:00", termStart: "2026-09-08", termEnd: "2026-12-05" },
    { course: "CPSC 121", kind: "lab", days: ["MO"], startTime: "09:00", endTime: "10:00", termStart: "2026-09-08", termEnd: "2026-12-05" },
    { course: "MATH 100", kind: "lecture", days: ["TU", "TH"], startTime: "13:00", endTime: "14:00", termStart: "2026-09-08", termEnd: "2026-12-05" },
  ];
  const monday = new Date(2026, 8, 14); // a Monday within term
  const found = selectMeetingsOn(meetings, monday);
  assert.deepEqual(found.map((m) => m.kind), ["lab", "lecture"]); // 09:00 before 10:00
  assert.equal(selectMeetingsOn(meetings, new Date(2026, 8, 19)).length, 0); // Saturday - nothing meets weekends
});

test("selectMeetingsOn: excludes a matching weekday outside the meeting's term range", () => {
  const meetings = [
    { course: "CPSC 121", kind: "lecture", days: ["MO"], startTime: "10:00", endTime: "11:00", termStart: "2026-09-08", termEnd: "2026-12-05" },
  ];
  const beforeTerm = new Date(2026, 7, 3); // a Monday, but before termStart
  const afterTerm = new Date(2026, 11, 14); // a Monday, but after termEnd
  assert.deepEqual(selectMeetingsOn(meetings, beforeTerm), []);
  assert.deepEqual(selectMeetingsOn(meetings, afterTerm), []);
});

test("selectCurrentTermMeetings: separates Term 1 from Term 2 by whether `now` falls in each meeting's own term", () => {
  // A real Workday export carries every term a student's ever had a
  // schedule for in the same file - Term 1 and Term 2 courses must not
  // show up mixed together once Term 1 has ended.
  const term1 = { course: "CPSC 121", kind: "lecture", days: ["MO"], startTime: "10:00", endTime: "11:00", termStart: "2026-09-08", termEnd: "2026-12-05" };
  const term2 = { course: "CPSC 213", kind: "lecture", days: ["MO"], startTime: "10:00", endTime: "11:00", termStart: "2027-01-11", termEnd: "2027-04-09" };
  const meetings = [term1, term2];

  const duringTerm1 = new Date(2026, 9, 14);
  assert.deepEqual(selectCurrentTermMeetings(meetings, duringTerm1), [term1]);

  const duringTerm2 = new Date(2027, 1, 8);
  assert.deepEqual(selectCurrentTermMeetings(meetings, duringTerm2), [term2]);

  const betweenTerms = new Date(2026, 11, 20); // after Term 1 ends, before Term 2 starts
  assert.deepEqual(selectCurrentTermMeetings(meetings, betweenTerms), []);
});

test("selectDaySchedule: weaves that day's classes and due items into one chronological list", () => {
  const monday = new Date(2026, 8, 14); // a Monday within term
  const meetings = [
    { course: "CPSC 121", kind: "lecture", days: ["MO"], startTime: "10:00", endTime: "11:00", termStart: "2026-09-08", termEnd: "2026-12-05" },
  ];
  const items = [
    { id: 1, title: "Problem Set 3", kind: "assignment", course: "CPSC 121", due: new Date(2026, 8, 14, 23, 59).toISOString(), urgency: "medium" },
    { id: 2, title: "Reading response", kind: "reading", course: "ENGL 110", due: new Date(2026, 8, 14, 8, 30).toISOString(), urgency: "low" },
    { id: 3, title: "Not this day", kind: "quiz", course: "MATH 100", due: new Date(2026, 8, 15, 8, 0).toISOString(), urgency: "low" },
  ];
  const schedule = selectDaySchedule(items, meetings, monday);
  // 08:30 reading, 10:00 lecture, 23:59 assignment - due items interleaved
  // with the class by actual time, not bucketed separately; the 15th's item
  // (a different day) is excluded.
  assert.deepEqual(
    schedule.map((e) => (e.kind === "meeting" ? e.meeting.course : e.item.title)),
    ["Reading response", "CPSC 121", "Problem Set 3"],
  );
  assert.deepEqual(schedule.map((e) => e.kind), ["item", "meeting", "item"]);
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

test("syncKeyFromHash: takes a well-formed #sync key, ignores anything else", () => {
  const key = "a".repeat(20) + "-_B" + "9".repeat(20); // 43 urlsafe chars
  assert.equal(syncKeyFromHash(`#sync=${key}`), key);
  assert.equal(syncKeyFromHash(`#tab=all&sync=${key}`), key);
  assert.equal(syncKeyFromHash("#sync=short"), null);
  assert.equal(syncKeyFromHash(`#sync=${key.slice(0, 40)}!!!`), null);
  assert.equal(syncKeyFromHash(""), null);
  assert.equal(syncKeyFromHash(undefined), null);
});
