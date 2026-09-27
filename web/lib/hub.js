// Data layer for web/. Two modes, chosen by config (issue #31):
//   - Local mode: NEXT_PUBLIC_HUB_API is set -> talk to Jacky's hub/api.py
//     over http://127.0.0.1:<port>, which returns rows already ranked and
//     annotated with status/urgency from hub.models (never recomputed here).
//   - Sample mode (hosted Vercel default): no API reachable, fixed fake data.

const URGENCY_ORDER = ["overdue", "critical", "high", "medium", "low"];

// Kinds a student can flag as "always show me these first" in Settings -
// mirrors the vocabulary hub/models.py's _WEIGHT_KEYWORDS treats as
// high-stakes (final/midterm/exam, project/essay/paper, assignment/homework,
// quiz, reading), collapsed to the `kind` values items actually carry
// (see hub/canvas.py's KINDS map and hub.js's own CATEGORY_FOR below).
export const PREFERRED_KIND_OPTIONS = [
  { id: "exam", label: "Exams" },
  { id: "quiz", label: "Quizzes" },
  { id: "assignment", label: "Assignments" },
  { id: "reading", label: "Readings" },
  { id: "project", label: "Projects / essays" },
];

const PREFERRED_KINDS_COOKIE = "hub-preferred-kinds";

// Pure: turn the cookie's raw comma-separated value into a Set, dropping
// anything that isn't a known kind id so a stale or hand-edited cookie can't
// smuggle in junk. Kept separate from the document.cookie read/write below so
// the actual parsing logic is unit-testable without a DOM.
export function parsePreferredKinds(raw) {
  if (!raw) return new Set();
  const valid = new Set(PREFERRED_KIND_OPTIONS.map((o) => o.id));
  return new Set(
    raw.split(",").map((s) => s.trim()).filter((s) => valid.has(s)),
  );
}

// Not pure (touches document.cookie) - no test for these two, per the
// pattern in hub.test.mjs; parsePreferredKinds carries the logic that can be
// tested.
export function readPreferredKindsCookie() {
  if (typeof document === "undefined") return new Set();
  const match = document.cookie.match(/(?:^|; )hub-preferred-kinds=([^;]*)/);
  return parsePreferredKinds(match ? decodeURIComponent(match[1]) : "");
}

export function writePreferredKindsCookie(kinds) {
  if (typeof document === "undefined") return;
  const value = encodeURIComponent(Array.from(kinds).join(","));
  // 1 year, path=/ so it's readable app-wide; samesite=lax is plenty for a
  // same-site preference with no cross-site use.
  document.cookie = `${PREFERRED_KINDS_COOKIE}=${value}; path=/; max-age=31536000; samesite=lax`;
}

export function apiBase() {
  return process.env.NEXT_PUBLIC_HUB_API || null;
}

export function isLocalMode() {
  return apiBase() !== null;
}

// Same 5 rows as app.py's sample_conn(), plus urgency/status precomputed
// ONCE by actually running hub.models.classify_urgency()/status_of() against
// them (see the reconciliation notes in this repo's history) - not
// reimplemented here. These are frozen labels for illustration, not a live
// computation, since we deliberately don't duplicate that logic in JS.
const SAMPLE_ROWS = [
  { course: "CPSC 121", title: "Problem Set 3", kind: "assignment", dueInDays: 2, urgency: "medium", status: "soon" },
  { course: "CPSC 121", title: "Quiz 2", kind: "quiz", dueInDays: 4, urgency: "low", status: "upcoming" },
  { course: "MATH 100", title: "Midterm 1", kind: "exam", dueInDays: 9, urgency: "medium", status: "upcoming" },
  { course: "ENGL 110", title: "Read ch. 4", kind: "reading", dueInDays: 1, urgency: "medium", status: "soon" },
  { course: "MATH 100", title: "WeBWorK 3", kind: "assignment", dueInDays: -1, urgency: "overdue", status: "overdue" },
];

const CATEGORY_FOR = {
  assignment: "task",
  announcement: "task",
  quiz: "deadline",
  exam: "deadline",
  event: "deadline",
  break: "deadline",
  payment: "deadline",
  reading: "material",
  textbook: "material",
};

const SAMPLE_COURSES = [
  { code: "CPSC 121", term: "2026W1", title: "Models of Computation", grade: 84.5 },
  { code: "MATH 100", term: "2026W1", title: "Differential Calculus", grade: null },
  { code: "ENGL 110", term: "2026W1", title: "Approaches to Literature", grade: null },
];

function sampleItems() {
  const now = Date.now();
  return SAMPLE_ROWS.map((row, i) => ({
    id: i,
    course: row.course,
    category: CATEGORY_FOR[row.kind] ?? "task",
    kind: row.kind,
    title: row.title,
    due: new Date(now + row.dueInDays * 24 * 60 * 60 * 1000).toISOString(),
    url: `https://example.invalid/${i}`,
    done: false,
    urgency: row.urgency,
    status: row.status,
  }));
}

// Backend rows from hub/api.py don't have urgency/status yet (Jacky's part
// of #31, still in progress) - normalise what's there, leave the rest
// undefined rather than guess at it client-side.
function normaliseApiItem(row, i) {
  return {
    id: i,
    course: row.course,
    category: row.category,
    kind: row.kind,
    title: row.title,
    due: row.due,
    url: row.url,
    source: row.source,
    done: row.done ?? null,
    urgency: row.urgency ?? undefined,
    status: row.status ?? undefined,
  };
}

// useSample forces sample data even when a local API is configured - this is
// the "Sample data" toggle (app.py parity), not just the env var. The env
// var controls whether local mode is *possible* at all (and so whether the
// toggle/Connect buttons show); the toggle controls what's actually fetched.
export async function fetchUpcoming(useSample) {
  const base = apiBase();
  if (!base || useSample) return sampleItems();
  const res = await fetch(`${base}/api/upcoming`);
  if (!res.ok) throw new Error(`GET /api/upcoming failed: ${res.status}`);
  const rows = await res.json();
  return rows.map(normaliseApiItem);
}

export async function fetchCourses(useSample) {
  const base = apiBase();
  if (!base || useSample) return SAMPLE_COURSES;
  const res = await fetch(`${base}/api/courses`);
  if (!res.ok) throw new Error(`GET /api/courses failed: ${res.status}`);
  return res.json();
}

export async function connectCanvas() {
  const base = apiBase();
  if (!base) throw new Error("connectCanvas() only works in local mode");
  const res = await fetch(`${base}/api/connect/canvas`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/connect/canvas failed: ${res.status}`);
  return res.json();
}

export async function connectPrairieLearn() {
  const base = apiBase();
  if (!base) throw new Error("connectPrairieLearn() only works in local mode");
  const res = await fetch(`${base}/api/connect/prairielearn`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/connect/prairielearn failed: ${res.status}`);
  return res.json();
}

// Sort by urgency (matches hub.logic.sort_items's order) when the backend
// (or sample data) provides it; items without it yet (API not upgraded)
// fall back to due-date order rather than a guessed urgency.
//
// preferredKinds (a Set of `kind` ids, from Settings' "what's urgent to you"
// preference) only breaks ties *within* an urgency band - a stable secondary
// key, applied before falling back to due date. It never moves an item
// across bands or touches the urgency label itself: that math is
// hub/models.py's classify_urgency() and stays backend-only, per the note
// above SAMPLE_ROWS. ponytail: a real "boost" would re-run the weight/hours
// formula with a per-student multiplier server-side; this client-only nudge
// is the cheap version for a preference toggle, not a ranking rewrite.
export function sortItems(items, preferredKinds = new Set()) {
  return [...items].sort((a, b) => {
    const aRank = a.urgency ? URGENCY_ORDER.indexOf(a.urgency) : URGENCY_ORDER.length;
    const bRank = b.urgency ? URGENCY_ORDER.indexOf(b.urgency) : URGENCY_ORDER.length;
    if (aRank !== bRank) return aRank - bRank;
    const aPreferred = preferredKinds.has(a.kind) ? 0 : 1;
    const bPreferred = preferredKinds.has(b.kind) ? 0 : 1;
    if (aPreferred !== bPreferred) return aPreferred - bPreferred;
    return new Date(a.due) - new Date(b.due);
  });
}

// "Overdue" for the Hide-overdue toggle: prefer the backend's real status,
// and only fall back to a plain date check (not urgency - that stays
// backend-only) when status hasn't arrived yet.
export function isOverdue(item, now) {
  if (item.status) return item.status === "overdue";
  if (item.done) return false;
  return item.due && new Date(item.due) < now;
}

// Completed items never show, regardless of Hide overdue - matches app.py's
// df2e178 rule exactly. Prefer the backend's status; fall back to the raw
// done flag if status hasn't arrived yet.
export function isDone(item) {
  if (item.status) return item.status === "done";
  return Boolean(item.done);
}

// Display only - app.py capitalises urgency/status labels ("Overdue", not
// "overdue"); values themselves stay lowercase everywhere else (comparisons,
// URGENCY_ORDER, the backend's own strings).
export function displayLabel(value) {
  if (!value) return "—";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

// Display only - same category as displayLabel: formats a raw value (an
// ISO due date) for a person to read, decides nothing.
export function formatDue(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-CA", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// --- Processing layer -------------------------------------------------
// Everything below is pure: given state, compute what to render. page.js
// owns *when* state changes (fetch, toggle, import); this owns *what the
// data means* once you have it. Neither of these functions touches React,
// fetch, or the DOM - they're plain data in, data out, so they're testable
// on their own and can't reach back into component state by accident.

// Merge courses by code - used both to combine fetched + imported courses
// for rendering, and to fold a fresh import into what's already imported.
// Workday never carries a grade, so an existing one (e.g. from Canvas)
// isn't blanked out by a re-import.
export function mergeCourses(base, incoming) {
  const byCode = new Map(base.map((c) => [c.code, c]));
  for (const c of incoming) {
    const existing = byCode.get(c.code);
    byCode.set(c.code, existing ? { ...existing, ...c, grade: c.grade ?? existing.grade } : c);
  }
  return Array.from(byCode.values());
}

// Completed items never show anywhere, regardless of Hide overdue (matches
// app.py's df2e178 rule) - applied once so every tab and the Courses tab's
// per-course lists see the same set.
export function selectActiveItems(items) {
  return items.filter((item) => !isDone(item));
}

// The flat item list for a given tab/toggle/limit combination. Expects
// already-active (non-done) items - see selectActiveItems.
export function selectVisibleItems(items, { tab, hideOverdue, showN, now, preferredKinds }) {
  return sortItems(items, preferredKinds)
    .filter((item) => tab === "all" || tab === "courses" || item.category === tab)
    .filter((item) => !hideOverdue || !isOverdue(item, now))
    .slice(0, showN);
}

// One course's own items, ranked - what the Courses tab's per-course table
// needs. Expects already-active (non-done) items - see selectActiveItems.
export function selectCourseItems(items, courseCode, preferredKinds) {
  return sortItems(items.filter((item) => item.course === courseCode), preferredKinds);
}

// The single most urgent active item, or null. Expects already-active
// (non-done) items - see selectActiveItems.
export function selectNextUp(items, preferredKinds) {
  return sortItems(items, preferredKinds)[0] ?? null;
}

// The 7 dates (Mon-Sun) of the week containing `now` - what a calendar-week
// widget needs, computed rather than hardcoded so it's never stale.
export function weekDates(now) {
  const day = (now.getDay() + 6) % 7; // Mon=0 .. Sun=6
  const monday = new Date(now);
  monday.setHours(0, 0, 0, 0);
  monday.setDate(monday.getDate() - day);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return d;
  });
}

// Whether any active item is due on the given calendar date (local time).
export function hasItemDueOn(items, date) {
  return items.some((item) => item.due && sameDay(new Date(item.due), date));
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// What Settings' Connections list needs: one row per known provider, derived
// from the data actually on hand rather than a separately-tracked "connected"
// flag (sample data never sets item.source, so it correctly shows as
// disconnected everywhere). Workday isn't a login - it's a file the student
// already has - so "connected" means "imported this session", not "logged in".
export function selectConnections(items, importedCourses) {
  const countBySource = (source) => items.filter((item) => item.source === source).length;
  return [
    { id: "canvas", label: "Canvas", connected: countBySource("canvas") > 0, detail: `${countBySource("canvas")} item${countBySource("canvas") === 1 ? "" : "s"}` },
    { id: "prairielearn", label: "PrairieLearn", connected: countBySource("prairielearn") > 0, detail: `${countBySource("prairielearn")} item${countBySource("prairielearn") === 1 ? "" : "s"}` },
    { id: "workday", label: "Workday", connected: importedCourses.length > 0, detail: `${importedCourses.length} course${importedCourses.length === 1 ? "" : "s"} imported` },
  ];
}
