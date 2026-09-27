// Data layer for web/. Two modes, chosen by config (issue #31):
//   - Local mode: NEXT_PUBLIC_HUB_API is set -> talk to Jacky's hub/api.py
//     over http://127.0.0.1:<port>, which returns rows already ranked and
//     annotated with status/urgency from hub.models (never recomputed here).
//   - Hosted (no local API), Sample on: rows come from the hosted GET
//     /api/demo (web/api/demo.py): a fake "Demo Student" run through the
//     real hub/ adapters and fusion. If that fails, the fixed SAMPLE_ROWS
//     below, so the page never breaks.
//   - Hosted, Sample off: nothing fake, ever. Only the student's real
//     sources (the hosted store's synced rows via fetchHostedStore(), the
//     Canvas calendar feed, a Workday import) - page.js merges those in;
//     these fetchers return nothing.

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
// Hosted Sample mode only (no local API): GET /api/demo once per page load,
// shared by fetchUpcoming/fetchAnnouncements/fetchCourses. Resolves to null
// on any failure so each caller falls back to its built-in sample data -
// never throws. `fetchImpl` is injectable for tests.
let demoPromise = null;

export function fetchDemo(fetchImpl = globalThis.fetch) {
  if (!demoPromise) {
    demoPromise = (async () => {
      try {
        const res = await fetchImpl("/api/demo");
        if (!res.ok) return null;
        const body = await res.json();
        if (!body || !Array.isArray(body.items)) return null;
        return {
          items: body.items.map(normaliseApiItem),
          announcements: Array.isArray(body.announcements) ? body.announcements.map(normaliseApiItem) : [],
          courses: Array.isArray(body.courses) ? body.courses : SAMPLE_COURSES,
          meetings: Array.isArray(body.schedule) ? body.schedule.map(normaliseApiMeeting) : [],
        };
      } catch {
        return null;
      }
    })();
  }
  return demoPromise;
}

// Test-only: forget the cached /api/demo response.
export function resetDemoCache() {
  demoPromise = null;
}

export async function fetchUpcoming(useSample) {
  const base = apiBase();
  if (!base) return useSample ? ((await fetchDemo())?.items ?? sampleItems()) : [];
  if (useSample) return sampleItems();
  const res = await fetch(`${base}/api/upcoming`);
  if (!res.ok) throw new Error(`GET /api/upcoming failed: ${res.status}`);
  const rows = await res.json();
  return rows.map(normaliseApiItem);
}

// Announcements never carry a due date (they're informational, not a task -
// see hub/canvas.py's to_item()), so they're a separate feed from
// fetchUpcoming() rather than items mixed into it. The hosted demo carries
// its own; the SAMPLE_ROWS fallback has none - none of them is
// announcement-shaped, so there's nothing to fake.
export async function fetchAnnouncements(useSample) {
  const base = apiBase();
  if (!base) return useSample ? ((await fetchDemo())?.announcements ?? []) : [];
  if (useSample) return [];
  const res = await fetch(`${base}/api/announcements`);
  if (!res.ok) throw new Error(`GET /api/announcements failed: ${res.status}`);
  const rows = await res.json();
  return rows.map(normaliseApiItem);
}

export async function fetchCourses(useSample) {
  const base = apiBase();
  if (!base) return useSample ? ((await fetchDemo())?.courses ?? SAMPLE_COURSES) : [];
  if (useSample) return SAMPLE_COURSES;
  const res = await fetch(`${base}/api/courses`);
  if (!res.ok) throw new Error(`GET /api/courses failed: ${res.status}`);
  return res.json();
}

// /api/schedule's row shape (hub/api.py's _schedule, snake_case) -> the
// camelCase Meeting shape web/lib/workday.js's import produces, so the
// Schedule and Calendar views read both the same way.
function normaliseApiMeeting(row) {
  return {
    course: row.course, kind: row.kind, days: row.days,
    startTime: row.start_time, endTime: row.end_time, location: row.location,
    termStart: row.term_start, termEnd: row.term_end, source: row.source,
  };
}

// The demo student's recurring class meetings - hosted Sample mode only.
// Local mode's /api/schedule isn't wired into web/ yet, and Sample off never
// shows anything fake, so both get [] (a Workday import still works as before).
export async function fetchDemoMeetings(useSample) {
  if (apiBase() || !useSample) return [];
  return (await fetchDemo())?.meetings ?? [];
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

export async function connectPrairieLearnOk() {
  const base = apiBase();
  if (!base) throw new Error("connectPrairieLearnOk() only works in local mode");
  const res = await fetch(`${base}/api/connect/prairielearn_ok`, { method: "POST" });
  if (!res.ok) throw new Error(`POST /api/connect/prairielearn_ok failed: ${res.status}`);
  return res.json();
}

// For a PrairieLearn instance we don't have a quick-connect button for -
// any department can self-host their own (hub/prairielearn.py's
// resolve_campus() accepts a full URL, not just a known key). `domain`
// should be a bare "https://..." origin; the backend validates and rejects
// anything else before it ever reaches a real login window.
export async function connectPrairieLearnCustom(domain) {
  const base = apiBase();
  if (!base) throw new Error("connectPrairieLearnCustom() only works in local mode");
  const res = await fetch(`${base}/api/connect/prairielearn_custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || `POST /api/connect/prairielearn_custom failed: ${res.status}`);
  return body;
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

// Identity for an Item with no id of its own - rule 4's (source, url),
// same key mergeItems already upserts by. Shared here so a client-only
// "mark as done" override (manuallyDoneKeys) can key off the same identity
// without inventing a second one.
export function itemKey(item) {
  return `${item.source} ${item.url}`;
}

// Completed items never show, regardless of Hide overdue - matches app.py's
// df2e178 rule exactly. A manual check-off (manuallyDoneKeys, a student
// crossing something off their own dashboard - #98) wins outright: it's a
// personal, client-only override that never reaches Canvas/PrairieLearn/
// Workday, so it must never depend on what the backend's own status says.
// Otherwise, prefer the backend's status; fall back to the raw done flag
// if status hasn't arrived yet.
export function isDone(item, manuallyDoneKeys = []) {
  if (manuallyDoneKeys.includes(itemKey(item))) return true;
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

// Merge items by (source, url) - rule 4's identity - the same role
// mergeCourses plays for Workday's imported courses, here for the Canvas
// calendar-feed's fetched items (#47) sitting alongside whatever
// fetchUpcoming() already loaded.
export function mergeItems(base, incoming) {
  const byKey = new Map(base.map((i) => [itemKey(i), i]));
  for (const i of incoming) {
    byKey.set(itemKey(i), i);
  }
  return Array.from(byKey.values());
}

// Merge recurring class meetings (#85) - Meeting has no (source, url)
// identity like an Item, so the closest natural key is the same one
// hub/db.py's `meetings` table uses: course + kind + its specific weekly
// slot (days + start time), so re-importing an updated export replaces a
// changed meeting instead of duplicating it.
export function mergeMeetings(base, incoming) {
  const key = (m) => `${m.course} ${m.kind} ${m.days.join(",")} ${m.startTime}`;
  const byKey = new Map(base.map((m) => [key(m), m]));
  for (const m of incoming) {
    byKey.set(key(m), m);
  }
  return Array.from(byKey.values());
}

// Canvas calendar-feed connect (#47) - works with no local backend at all,
// so it's the only Canvas path that also works on the hosted Vercel site.
// The feed URL is a secret (works like a password): after one successful
// POST it lives only in an httpOnly cookie scoped to /api/feed (see
// hub/ics.py's feed_request()), so no script on this page can read it back.
// Accepts either a bare item array or {items: [...]}.
//
// Local mode's /api/feed lives on hub/api.py (a different origin, :8000,
// same site), so the cookie needs credentials "include" there; hosted mode
// is this page's own origin, so "same-origin" is enough.
function feedRequest(method, body, fetchImpl) {
  const base = apiBase();
  const init = { method, credentials: base ? "include" : "same-origin" };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  return fetchImpl(base ? `${base}/api/feed` : "/api/feed", init);
}

async function feedRows(res) {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `/api/feed failed: ${res.status}`);
  const rows = Array.isArray(body) ? body : (body.items ?? []);
  return rows.map(normaliseApiItem);
}

// Connect: POST the pasted URL once. The server sets the cookie only if the
// fetch worked; the caller should drop the URL right after.
export async function connectCanvasFeed(url, fetchImpl = globalThis.fetch) {
  return feedRows(await feedRequest("POST", { url }, fetchImpl));
}

// Refresh from the cookie. null = nothing connected (404), not an error.
export async function refreshCanvasFeed(fetchImpl = globalThis.fetch) {
  const res = await feedRequest("GET", undefined, fetchImpl);
  if (res.status === 404) return null;
  return feedRows(res);
}

// Disconnect: the server clears the cookie. Never throws.
export async function disconnectCanvasFeed(fetchImpl = globalThis.fetch) {
  try {
    await feedRequest("DELETE", undefined, fetchImpl);
  } catch {
    // the UI has already forgotten the items; nothing else to undo
  }
}

// One-time move off the old localStorage key: POST it so the server can set
// the cookie, deleting the key first whatever happens, so the secret never
// lingers in browser-readable storage. Resolves once the POST settles.
export const LEGACY_FEED_KEY = "gather-canvas-feed-url";

export async function migrateLegacyFeedUrl(storage, fetchImpl = globalThis.fetch) {
  let url = null;
  try {
    url = storage.getItem(LEGACY_FEED_KEY);
    // Removed before the POST, not after, so even a tab closed mid-request
    // doesn't leave the secret behind.
    storage.removeItem(LEGACY_FEED_KEY);
  } catch {
    // storage unavailable (private window, blocked site data)
  }
  if (!url) return;
  try {
    await connectCanvasFeed(url, fetchImpl);
  } catch {
    // a dead or expired link: dropped either way
  }
}

// Hosted store (web/api/sync.py, items.py, session.py) - the extension syncs
// a student's data under a sync key it generated; the dashboard is handed
// that key once as a #sync=<key> fragment (fragments never reach server
// logs), trades it for an httpOnly cookie, and reads rows back with it.
// Until hosted storage is provisioned those routes answer 503, and every
// caller here treats any non-200 as "no hosted data" - the dashboard just
// keeps its existing behaviour.
export function syncKeyFromHash(hash) {
  const key = new URLSearchParams((hash || "").replace(/^#/, "")).get("sync");
  return key && /^[A-Za-z0-9_-]{43,128}$/.test(key) ? key : null;
}

export async function startHostedSession(key) {
  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  return res.ok;
}

// Push this browser's currently-loaded data - typically real Canvas/
// PrairieLearn rows from a local Playwright login (hub/site.py), only ever
// possible in local mode - to the hosted store, so it shows up on the
// hosted dashboard too. Grouped by source since /api/sync's body carries
// exactly one source per call (hub/hosted.py's parse_sync). Returns the
// total item count actually stored.
export async function pushToHostedStore(hostedBase, key, items, courses) {
  const bySource = new Map();
  for (const item of items) {
    if (!item.source) continue;
    if (!bySource.has(item.source)) bySource.set(item.source, []);
    bySource.get(item.source).push({
      course: item.course, category: item.category, kind: item.kind, title: item.title,
      due: item.due, url: item.url, source: item.source, done: item.done ?? null,
    });
  }
  let stored = 0;
  for (const [source, sourceItems] of bySource) {
    const res = await fetch(`${hostedBase}/api/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({ source, courses, items: sourceItems }),
    });
    if (!res.ok) throw new Error(`Push failed for ${source}: ${res.status}`);
    stored += (await res.json()).items ?? 0;
  }
  return stored;
}

// {items, courses} from the hosted store, or null when there's no session
// (401) or no store (503) - never throws for those.
export async function fetchHostedStore() {
  const res = await fetch("/api/items", { credentials: "same-origin" });
  if (!res.ok) return null;
  const body = await res.json();
  return { items: (body.items ?? []).map(normaliseApiItem), courses: body.courses ?? [] };
}

// Completed items never show anywhere, regardless of Hide overdue (matches
// app.py's df2e178 rule) - applied once so every tab and the Courses tab's
// per-course lists see the same set.
export function selectActiveItems(items, manuallyDoneKeys = []) {
  return items.filter((item) => !isDone(item, manuallyDoneKeys));
}

// A hidden course (Settings - for the old/inactive enrollments Canvas keeps
// listing) disappears everywhere: the sidebar, filter chips, Courses tab,
// and any of its items in every other view - not just its own row. This is
// display-only, client-side (hiddenCourses is never sent anywhere) - the
// course and its items stay exactly as fetched in hub.db.
export function selectVisibleCourses(courses, hiddenCourses) {
  return courses.filter((c) => !hiddenCourses.includes(c.code));
}

export function hideCourseItems(items, hiddenCourses) {
  return items.filter((item) => !hiddenCourses.includes(item.course));
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

// The calendar grid for the month containing `monthDate`: 6 weeks of 7 dates
// (Mon-Sun), padded with the trailing days of the previous/next month so
// every row is full - what a month view needs to render a rectangular grid.
// Fixed at 6 weeks (42 cells) rather than 4-6 depending on the month, so the
// grid never resizes as the student pages between months.
// ponytail: plain Date math instead of a date library - this repo has none,
// and a month grid is just "first day's weekday offset, then walk forward".
export function monthGrid(monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const startOffset = (firstOfMonth.getDay() + 6) % 7; // Mon=0..Sun=6
  const gridStart = new Date(year, month, 1 - startOffset);
  const cells = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return { date: d, inMonth: d.getMonth() === month };
  });
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

// Active items due on one calendar date (local time) - the Calendar page's
// per-day list once a cell is clicked. Expects already-active (non-done)
// items - see selectActiveItems.
export function selectItemsDueOn(items, date) {
  return sortItems(items.filter((item) => item.due && sameDay(new Date(item.due), date)));
}

const JS_DAY_TO_CODE = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]; // Date#getDay(): 0=Sunday

function localISODate(date) {
  // Local calendar date, not date.toISOString() (which is UTC and can land
  // on the wrong day near midnight) - matches the "YYYY-MM-DD" termStart/
  // termEnd strings parseWorkdaySchedule produces, so a plain string
  // comparison is enough to check whether `date` falls in a Meeting's term.
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// A real Workday export carries every term the student has ever had a
// schedule for (Term 1 and Term 2 both show up in the same "Meeting
// Patterns" column), each meeting tagged with its own real term_start/
// term_end - so a weekly-template view (the Schedule tab) needs this filter
// just as much as a specific clicked date does, or a Term 1 course that
// ended weeks ago still shows up mixed in with current Term 2 ones.
export function selectCurrentTermMeetings(meetings, now) {
  const iso = localISODate(now);
  return meetings.filter((m) => iso >= m.termStart && iso <= m.termEnd);
}

// A recurring class Meeting has no single date, just a day-of-week + a term
// range - this is the Calendar page's per-day equivalent of selectItemsDueOn,
// for the Workday schedule side panel on a clicked day.
export function selectMeetingsOn(meetings, date) {
  const code = JS_DAY_TO_CODE[date.getDay()];
  return selectCurrentTermMeetings(meetings, date)
    .filter((m) => m.days.includes(code))
    .sort((a, b) => a.startTime.localeCompare(b.startTime));
}

// The Calendar day panel's actual content: that day's Workday class
// meetings AND its due items, woven into one chronological list (not two
// separate stacked lists) - "what does my day look like", classes and
// deadlines together in the order they'd actually happen. Each entry keeps
// its original shape under `meeting`/`item` so the caller can render either
// kind; `time` is "HH:MM" for both, so a plain string sort interleaves them
// correctly (a due item's time comes from its own due instant, not
// selectItemsDueOn's urgency-first order).
export function selectDaySchedule(items, meetings, date) {
  const meetingEntries = selectMeetingsOn(meetings, date).map((meeting) => ({ kind: "meeting", time: meeting.startTime, meeting }));
  const itemEntries = selectItemsDueOn(items, date).map((item) => {
    const due = new Date(item.due);
    const time = `${String(due.getHours()).padStart(2, "0")}:${String(due.getMinutes()).padStart(2, "0")}`;
    return { kind: "item", time, item };
  });
  return [...meetingEntries, ...itemEntries].sort((a, b) => a.time.localeCompare(b.time));
}

// What Settings' Connections list needs: one row per known provider, derived
// from the data actually on hand rather than a separately-tracked "connected"
// flag (sample data never sets item.source, so it correctly shows as
// disconnected everywhere). Workday isn't a login - it's a file the student
// already has - so "connected" means "imported this session", not "logged in".
const KNOWN_PROVIDERS = [
  { id: "canvas", label: "Canvas" },
  { id: "prairielearn", label: "PrairieLearn" },
  { id: "prairielearn_ok", label: "PrairieLearn (Okanagan)" },
];

function countOf(n, noun) {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

export function selectConnections(items, meetings) {
  const countBySource = (source) => items.filter((item) => item.source === source).length;
  const rows = KNOWN_PROVIDERS.map(({ id, label }) => ({ id, label, connected: countBySource(id) > 0, detail: countOf(countBySource(id), "item") }));

  // Any other source is a PrairieLearn instance a student pasted in
  // directly (hub/prairielearn.py's resolve_campus() accepts one) - a
  // hardcoded list can never cover every self-hosted instance, so these
  // show up dynamically instead of needing their own KNOWN_PROVIDERS entry.
  const knownIds = new Set(KNOWN_PROVIDERS.map((p) => p.id));
  const customSources = [...new Set(items.map((item) => item.source))].filter((s) => s && !knownIds.has(s));
  for (const source of customSources) {
    // hub/prairielearn.py's resolve_campus() keys a pasted instance
    // "pl-<host>" (never the bare host - that could collide with another
    // provider's own key), so strip the prefix back off for display only.
    const host = source.replace(/^pl-/, "");
    rows.push({ id: source, label: `PrairieLearn (${host})`, connected: true, detail: countOf(countBySource(source), "item") });
  }

  rows.push({ id: "workday", label: "Workday", connected: meetings.length > 0, detail: countOf(meetings.length, "class meeting") });
  return rows;
}
