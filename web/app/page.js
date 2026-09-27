"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  connectCanvas,
  connectPrairieLearn,
  connectPrairieLearnCustom,
  connectPrairieLearnOk,
  displayLabel,
  fetchAnnouncements,
  fetchDemoMeetings,
  connectCanvasFeed as postCanvasFeed,
  refreshCanvasFeed,
  disconnectCanvasFeed as deleteCanvasFeed,
  migrateLegacyFeedUrl,
  fetchCourses,
  fetchHostedStore,
  fetchUpcoming,
  formatDue,
  hasItemDueOn,
  hideCourseItems,
  isDone,
  isLocalMode,
  isOverdue,
  itemKey,
  mergeCourses,
  mergeItems,
  mergeMeetings,
  monthGrid,
  PREFERRED_KIND_OPTIONS,
  pushToHostedStore,
  readPreferredKindsCookie,
  selectActiveItems,
  selectConnections,
  selectCourseItems,
  selectItemsDueOn,
  selectCurrentTermMeetings,
  selectDaySchedule,
  selectNextUp,
  selectVisibleCourses,
  selectVisibleItems,
  startHostedSession,
  syncKeyFromHash,
  weekDates,
  writePreferredKindsCookie,
} from "../lib/hub";
import { parseWorkdaySchedule } from "../lib/workday";

function Icon({ name, className = "size-5" }) {
  const paths = {
    home: <><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10M9 20v-6h6v6" /></>,
    tasks: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="m8 9 2 2 4-4M8 16h8" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></>,
    courses: <><path d="m3 6 9-3 9 3-9 3-9-3Z" /><path d="M6 8v6c3 2 9 2 12 0V8M21 6v7" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    settings: <><path d="M4 6h10M18 6h2M4 18h10M18 18h2M4 12h4M12 12h8" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="16" cy="18" r="2" /></>,
    material: <><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
    announcement: <><path d="M9 5 3 9v6h6l6 4V1z" /><path d="M16 8a4.5 4.5 0 0 1 0 8" /></>,
  };
  return <svg aria-hidden="true" className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function AppButton({ children, className = "", onClick, ariaLabel, disabled }) {
  return <button aria-label={ariaLabel} disabled={disabled} className={`app-button ${className}`} onClick={onClick}>{children}</button>;
}

const NAV_ITEMS = [
  { label: "Overview", icon: "home", tab: "all" },
  { label: "Assignments", icon: "tasks", tab: "task" },
  { label: "Calendar", icon: "calendar", tab: "deadline" },
  { label: "Schedule", icon: "clock", tab: "schedule" },
  { label: "Materials", icon: "material", tab: "material" },
  { label: "Announcements", icon: "announcement", tab: "announcements" },
  { label: "Courses", icon: "courses", tab: "courses" },
];

const WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// A recurring weekly timetable (#85) - deliberately not tied to any specific
// calendar week, unlike the Calendar tab's month grid: a Meeting has no
// single date, just a day-of-week + time slot that repeats all term.
function ScheduleView({ meetings, now }) {
  if (meetings.length === 0) {
    return (
      <div className="p-10 text-center text-sm text-[var(--muted)]">
        No class schedule yet - import your Workday &quot;Current Schedule&quot; export in Settings.
      </div>
    );
  }
  // A real Workday export carries every term the student's ever had a
  // schedule for (Term 1 and Term 2 both show up in the same file) - only
  // show what's actually running right now, or a Term 1 course that ended
  // weeks ago stays mixed in with current Term 2 ones.
  const currentMeetings = selectCurrentTermMeetings(meetings, now);
  if (currentMeetings.length === 0) {
    return (
      <div className="p-10 text-center text-sm text-[var(--muted)]">
        No classes running right now - {meetings.length} meeting{meetings.length === 1 ? "" : "s"} imported, but none in the current term.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-7 sm:p-6">
      {WEEKDAY_CODES.map((code, i) => {
        const dayMeetings = currentMeetings
          .filter((m) => m.days.includes(code))
          .sort((a, b) => a.startTime.localeCompare(b.startTime));
        return (
          <div key={code}>
            <div className="mb-2 text-xs font-bold uppercase tracking-wide text-[var(--muted)]">{WEEKDAY_NAMES[i]}</div>
            <div className="space-y-2">
              {dayMeetings.map((m, idx) => (
                <div key={idx} className="rounded-lg border border-[var(--line)] bg-[var(--surface-soft)] p-2.5">
                  <div className="truncate text-xs font-bold">{m.course}</div>
                  <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{m.kind} &middot; {m.startTime}&ndash;{m.endTime}</div>
                  {m.location && <div className="truncate text-[0.7rem] text-[var(--muted)]">{m.location}</div>}
                </div>
              ))}
              {dayMeetings.length === 0 && <div className="text-[0.7rem] text-[var(--muted-light)]">&mdash;</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const THEMES = [
  { id: "everforest", label: "Everforest" },
  { id: "solarized", label: "Solarized" },
  { id: "gruvbox", label: "Gruvbox" },
  { id: "catppuccin", label: "Catppuccin" },
];

// Everforest's own values - what a freshly-picked "Custom" scheme starts
// from, so switching to it doesn't jump to something jarring before the
// student has changed anything.
const DEFAULT_CUSTOM_COLORS = { page: "#f3ead3", surface: "#fdf6e3", ink: "#2d353b", accent: "#3a6b52" };
const CUSTOM_COLOR_FIELDS = [
  { key: "page", label: "Background" },
  { key: "surface", label: "Cards" },
  { key: "ink", label: "Text" },
  { key: "accent", label: "Accent" },
];

const WEEKDAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];
const MAX_WORKDAY_FILE_BYTES = 5_000_000;
const MONTH_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// The Calendar nav tab's own page: a month grid of every active item's due
// date, plus the clicked day's items below. Owns its own displayed-month and
// selected-day state rather than lifting it into App(), since nothing else
// in the app needs to know which day is selected here.
function CalendarSection({ items, meetings, now, onToggleItemDone }) {
  const [monthDate, setMonthDate] = useState(new Date(now.getFullYear(), now.getMonth(), 1));
  const [selectedDate, setSelectedDate] = useState(null);

  const weeks = useMemo(() => monthGrid(monthDate), [monthDate]);
  const daySchedule = useMemo(() => (selectedDate ? selectDaySchedule(items, meetings, selectedDate) : []), [items, meetings, selectedDate]);

  function shiftMonth(delta) {
    setMonthDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
  }

  function goToday() {
    setMonthDate(new Date(now.getFullYear(), now.getMonth(), 1));
  }

  return (
    <>
      <div className="flex flex-col gap-4 border-b border-[var(--line)] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
        <div>
          <div className="text-xl font-bold tracking-tight">
            {monthDate.toLocaleDateString("en-CA", { month: "long", year: "numeric" })}
          </div>
          <div className="mt-1 text-sm text-[var(--muted)]">Deadlines across every connected course</div>
        </div>
        <div className="flex items-center gap-1">
          <AppButton ariaLabel="Previous month" onClick={() => shiftMonth(-1)} className="icon-button">
            <Icon name="arrow" className="size-4 rotate-180" />
          </AppButton>
          <AppButton onClick={goToday} className="filter-button">Today</AppButton>
          <AppButton ariaLabel="Next month" onClick={() => shiftMonth(1)} className="icon-button">
            <Icon name="arrow" className="size-4" />
          </AppButton>
        </div>
      </div>

      <div className="flex flex-col gap-6 p-5 sm:flex-row sm:p-6">
        <div className="min-w-0 flex-1">
          <div className="grid grid-cols-7 gap-1 text-center">
            {MONTH_WEEKDAY_LABELS.map((label) => (
              <div key={label} className="pb-2 text-[0.65rem] font-bold text-[var(--muted)]">{label}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {weeks.flat().map(({ date, inMonth }) => {
              const dueCount = selectItemsDueOn(items, date).length;
              const isToday = date.toDateString() === now.toDateString();
              const isSelected = selectedDate && date.toDateString() === selectedDate.toDateString();
              return (
                <button
                  key={date.toISOString()}
                  type="button"
                  aria-label={date.toLocaleDateString("en-CA", { weekday: "long", month: "long", day: "numeric" })}
                  onClick={() => setSelectedDate(date)}
                  className={`flex aspect-square flex-col items-center justify-center gap-1 rounded-lg text-sm font-semibold transition-colors hover:bg-[var(--surface-soft)] ${
                    inMonth ? "text-[var(--ink)]" : "text-[var(--muted-light)]"
                  } ${isToday ? "bg-[var(--accent-soft)] text-[var(--accent)]" : ""} ${
                    isSelected ? "ring-2 ring-[var(--accent)] ring-inset" : ""
                  }`}
                >
                  <span>{date.getDate()}</span>
                  {dueCount > 0 && <span className="size-1.5 rounded-full bg-[var(--accent)]" />}
                </button>
              );
            })}
          </div>
        </div>

        {selectedDate && (
          <div className="w-full shrink-0 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4 sm:w-64">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div className="text-sm font-bold">
                {selectedDate.toLocaleDateString("en-CA", { weekday: "long", month: "short", day: "numeric" })}
              </div>
              <AppButton ariaLabel="Close daily schedule" onClick={() => setSelectedDate(null)} className="icon-button">
                <span className="block text-xs font-bold leading-none">&times;</span>
              </AppButton>
            </div>
            <div className="space-y-2">
              {daySchedule.length === 0 ? (
                <div className="text-xs text-[var(--muted)]">Nothing scheduled or due this day.</div>
              ) : (
                daySchedule.map((entry, idx) =>
                  entry.kind === "meeting" ? (
                    <div key={idx} className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-2.5">
                      <div className="truncate text-xs font-bold">{entry.meeting.course}</div>
                      <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{entry.meeting.kind} &middot; {entry.meeting.startTime}&ndash;{entry.meeting.endTime}</div>
                      {entry.meeting.location && <div className="truncate text-[0.7rem] text-[var(--muted)]">{entry.meeting.location}</div>}
                    </div>
                  ) : (
                    <div key={idx} className="flex items-start gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface)] p-2.5">
                      <input
                        type="checkbox"
                        aria-label={`Mark "${entry.item.title}" as done`}
                        onChange={() => onToggleItemDone(entry.item)}
                        className="mt-0.5 size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                      />
                      <a href={entry.item.url} className="min-w-0 flex-1">
                        <div className="truncate text-xs font-bold">{entry.item.title}</div>
                        <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{entry.item.kind} &middot; due {entry.time}</div>
                        <div className="truncate text-[0.7rem] text-[var(--muted)]">{entry.item.course}</div>
                      </a>
                    </div>
                  ),
                )
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

const SOURCE_LABELS = {
  canvas: "Canvas",
  canvas_feed: "Canvas calendar feed",
  prairielearn: "PrairieLearn",
  prairielearn_ok: "PrairieLearn (Okanagan)",
  prairielearn_custom: "PrairieLearn",
  hosted: "Hub sync key",
  "sync-all": "Sync everywhere",
  push: "Push to hosted",
};

function SettingsPage({ theme, setTheme, customColors, setCustomColors, connections, sampleMode, onSampleModeChange, onConnected, onScheduleImported, allCourses, hiddenCourses, onToggleCourseHidden, feedConnected, feedItemCount, feedError, onConnectFeed, onDisconnectFeed, preferredKinds, onTogglePreferredKind, onConnectHosted, onSynced, hostedConnected, allItems, allCoursesForPush }) {
  const [term, setTerm] = useState("2026W1");
  const [workdayStatus, setWorkdayStatus] = useState(null);
  const [customDomain, setCustomDomain] = useState("");
  const [feedUrlInput, setFeedUrlInput] = useState("");
  const [hostedKeyInput, setHostedKeyInput] = useState("");
  const [extensionId, setExtensionId] = useState("");
  const [syncResults, setSyncResults] = useState(null);
  const [pushBase, setPushBase] = useState("https://hello-hacks26-one.vercel.app");
  const [pushKeyInput, setPushKeyInput] = useState("");
  const [pushStatus, setPushStatus] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const byId = Object.fromEntries(connections.map((c) => [c.id, c]));
  const FIXED_IDS = new Set(["canvas", "prairielearn", "prairielearn_ok", "workday"]);
  const customConnections = connections.filter((c) => !FIXED_IDS.has(c.id));

  useEffect(() => {
    setExtensionId(localStorage.getItem("hub-extension-id") || "");
  }, []);

  async function syncEverywhere() {
    const id = extensionId.trim();
    if (!/^[a-p]{32}$/.test(id)) throw new Error("Paste the extension ID from chrome://extensions first.");
    localStorage.setItem("hub-extension-id", id);
    if (!globalThis.chrome?.runtime?.sendMessage) {
      throw new Error("Extension unreachable. Load extension/ unpacked in Chrome and paste its ID from chrome://extensions.");
    }
    setSyncResults(null);
    // Unpacked installs have different IDs; save this browser's ID instead of guessing one.
    const progressTimer = setInterval(() => {
      chrome.runtime.sendMessage(id, {type: "SYNC_STATUS"}, (response) => {
        if (!chrome.runtime.lastError && response?.results?.length) setSyncResults(response.results);
      });
    }, 500);
    let reply;
    try {
      reply = await new Promise((resolve, reject) => {
        chrome.runtime.sendMessage(id, {type: "SYNC_ALL"}, (response) => {
          if (chrome.runtime.lastError) reject(new Error("Extension unreachable. Load extension/ unpacked in Chrome and check its ID."));
          else resolve(response);
        });
      });
    } finally {
      clearInterval(progressTimer);
    }
    if (!reply?.ok) throw new Error(reply?.error || "Extension did not respond.");
    setSyncResults(reply.results);
    if (reply.results.some((result) => result.ok)) await onSynced();
  }

  async function handleFile(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    // A real "View My Courses" export is a few hundred rows of text - a
    // generous cap well above that, mainly to reject something huge or
    // corrupted before it ever reaches the parser (defense in depth
    // alongside fixTruncatedRange's own sane-range clamp - see #49).
    if (file.size > MAX_WORKDAY_FILE_BYTES) {
      setWorkdayStatus(null);
      setError(`That file is too large (${Math.round(file.size / 1_000_000)}MB) - a real Workday export is much smaller than ${MAX_WORKDAY_FILE_BYTES / 1_000_000}MB.`);
      return;
    }
    try {
      const buf = await file.arrayBuffer();
      // Workday feeds the Schedule tab only, not the course list - Canvas/
      // PrairieLearn are the only sources with real assignment data, and a
      // Workday-only course (no items ever attached to it) showing up in
      // the sidebar/Courses tab would be misleading, not useful.
      const scheduleImported = parseWorkdaySchedule(buf, term);
      onScheduleImported(scheduleImported);
      setWorkdayStatus(
        scheduleImported.length > 0
          ? `Loaded ${scheduleImported.length} class meeting${scheduleImported.length === 1 ? "" : "s"}.`
          : "No class meetings found in that file.",
      );
    } catch (err) {
      setWorkdayStatus(null);
      setError(err.message);
    }
  }

  async function run(name, fn) {
    setBusy(name);
    setError(null);
    try {
      await fn();
      await onConnected();
    } catch (e) {
      // A person reads this - a human label, never an internal source id.
      setError(`${SOURCE_LABELS[name] ?? "Connect"}: ${e.message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
        <div className="mb-1 text-xl font-bold tracking-tight">What matters to you</div>
        <div className="mb-5 text-sm text-[var(--muted)]">
          Pick the kinds of work you personally treat as most urgent. Matching items get a Priority badge and move to the front of their urgency group - it doesn&apos;t change the urgency itself.
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {PREFERRED_KIND_OPTIONS.map((option) => (
            <label key={option.id} className="toggle-pill">
              <input
                type="checkbox"
                checked={preferredKinds.has(option.id)}
                onChange={() => onTogglePreferredKind(option.id)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
        <div className="mb-1 text-xl font-bold tracking-tight">Appearance</div>
        <div className="mb-5 text-sm text-[var(--muted)]">Pick a color scheme, or build your own.</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {THEMES.map((option) => (
            <AppButton key={option.id} ariaLabel={`Use ${option.label} theme`} onClick={() => setTheme(option.id)} className={`theme-option ${theme === option.id ? "theme-option-active" : ""}`}>
              <span className="flex gap-1">
                {[1, 2, 3].map((swatch) => <span key={swatch} className={`theme-swatch swatch-${option.id}-${swatch}`} />)}
              </span>
              <span className="mt-1.5 block truncate text-[0.65rem] font-bold">{option.label}</span>
            </AppButton>
          ))}
          <AppButton ariaLabel="Use a custom color scheme" onClick={() => setTheme("custom")} className={`theme-option ${theme === "custom" ? "theme-option-active" : ""}`}>
            <span className="flex gap-1">
              {[customColors.accent, customColors.page, customColors.surface].map((color, i) => (
                <span key={i} className="theme-swatch" style={{ background: color }} />
              ))}
            </span>
            <span className="mt-1.5 block truncate text-[0.65rem] font-bold">Custom</span>
          </AppButton>
        </div>

        {theme === "custom" && (
          <div className="mt-5 grid grid-cols-2 gap-4 border-t border-[var(--line)] pt-5 sm:grid-cols-4">
            {CUSTOM_COLOR_FIELDS.map((field) => (
              <label key={field.key} className="flex flex-col gap-1.5 text-xs font-bold text-[var(--muted)]">
                {field.label}
                <input
                  type="color"
                  value={customColors[field.key]}
                  onChange={(e) => setCustomColors({ ...customColors, [field.key]: e.target.value })}
                  className="h-9 w-full cursor-pointer rounded-md border border-[var(--line)] bg-transparent p-0.5"
                />
              </label>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
        <div className="mb-1 text-xl font-bold tracking-tight">Connections</div>
        <div className="mb-5 text-sm text-[var(--muted)]">
          {isLocalMode()
            ? "What's actually feeding your dashboard right now."
            : "This is the hosted demo: Sample data is a made-up demo student, run through Hub's real adapters. Connect your hosted data with a sync key, then refresh signed-in providers through the browser extension."}
        </div>

        <label className="toggle-pill mb-5 flex w-full items-center justify-between">
          <span>Sample data</span>
          <input type="checkbox" checked={sampleMode} onChange={(e) => onSampleModeChange(e.target.checked)} />
        </label>

        {!isLocalMode() && (
          <div className="mb-5 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
            {hostedConnected ? (
              <div className="text-sm font-bold text-[var(--success)]">Lauds connected - showing your synced data.</div>
            ) : (
              <>
                <div className="mb-2 text-sm font-bold">Paste your Lauds sync key</div>
                <div className="mb-3 text-xs text-[var(--muted)]">
                  Open the Lauds browser extension&apos;s popup and copy its &quot;Lauds sync key&quot; field.
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={hostedKeyInput}
                    onChange={(e) => setHostedKeyInput(e.target.value)}
                    placeholder="Sync key from the extension"
                    aria-label="Lauds sync key"
                    className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-xs"
                  />
                  <AppButton
                    disabled={busy !== null || !hostedKeyInput}
                    onClick={() => run("hosted", async () => {
                      const hasData = await onConnectHosted(hostedKeyInput.trim());
                      setHostedKeyInput("");
                      if (!hasData) setError("Connected, but no data has synced from the extension yet.");
                    })}
                    className="toggle-pill"
                  >
                    {busy === "hosted" ? "Connecting…" : "Connect"}
                  </AppButton>
                </div>
              </>
            )}
            <div className="mt-4 border-t border-[var(--line)] pt-4">
              <div className="mb-2 text-sm font-bold">Sync everywhere now</div>
              <div className="mb-3 text-xs text-[var(--muted)]">Load extension/ unpacked in Chrome, then paste its ID from chrome://extensions. Keep each connected provider signed in and open.</div>
              <div className="flex flex-wrap items-center gap-2">
                <input type="text" value={extensionId} onChange={(e) => setExtensionId(e.target.value)}
                  placeholder="Extension ID" aria-label="Extension ID"
                  className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-xs" />
                <AppButton disabled={busy !== null} onClick={() => run("sync-all", syncEverywhere)} className="toggle-pill">
                  Sync everywhere now
                </AppButton>
              </div>
              {busy === "sync-all" && <div className="mt-2 text-xs text-[var(--muted)]">Extension is syncing connected providers in sequence…</div>}
              {syncResults && <div className="mt-2 text-xs" aria-live="polite">
                {syncResults.length === 0 ? "No providers have synced through this extension yet. Connect one in its popup first." :
                  syncResults.map((result) => <div key={result.provider}>
                    {result.label}: {result.state === "pending" ? "Waiting" : result.state === "running" ? "Syncing" : result.ok || result.state === "done" && !result.error ? "Uploaded" : result.error}
                  </div>)}
              </div>}
            </div>
          </div>
        )}

        <div className="divide-y divide-[var(--line)]">
          <div className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3">
              <span className={`size-2.5 rounded-full ${byId.canvas.connected ? "bg-[var(--success)]" : "bg-[var(--muted-light)]"}`} />
              <div>
                <div className="font-bold">Canvas</div>
                <div className="text-xs text-[var(--muted)]">{byId.canvas.connected ? "Connected" : "Not connected"} &middot; {byId.canvas.detail}</div>
              </div>
            </div>
            {isLocalMode() && !sampleMode && (
              <AppButton disabled={busy !== null} onClick={() => run("canvas", connectCanvas)} className="toggle-pill">
                {busy === "canvas" ? "Signing in…" : byId.canvas.connected ? "Reconnect" : "Connect"}
              </AppButton>
            )}
          </div>

          {!sampleMode && (
            <div className="py-3">
              {feedConnected ? (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
                  <div>
                    <div className="text-sm font-bold">Calendar feed connected</div>
                    <div className="text-xs text-[var(--muted)]">
                      {feedError ? feedError : `${feedItemCount} item${feedItemCount === 1 ? "" : "s"} from your feed`}
                    </div>
                  </div>
                  <AppButton onClick={onDisconnectFeed} className="toggle-pill">Disconnect</AppButton>
                </div>
              ) : (
                <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
                  <div className="mb-2 text-sm font-bold">No local install? Paste your Canvas calendar feed instead</div>
                  <ol className="mb-3 list-decimal space-y-0.5 pl-4 text-xs text-[var(--muted)]">
                    <li>In Canvas, open <strong className="text-[var(--ink)]">Calendar</strong></li>
                    <li>Click <strong className="text-[var(--ink)]">Calendar Feed</strong> (bottom right)</li>
                    <li>Copy the link it gives you</li>
                  </ol>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={feedUrlInput}
                      onChange={(e) => setFeedUrlInput(e.target.value)}
                      placeholder="https://canvas.ubc.ca/feeds/calendars/....ics"
                      aria-label="Canvas calendar feed URL"
                      className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-xs"
                    />
                    <AppButton
                      disabled={busy !== null || !feedUrlInput}
                      onClick={() => run("canvas_feed", async () => { await onConnectFeed(feedUrlInput); setFeedUrlInput(""); })}
                      className="toggle-pill"
                    >
                      {busy === "canvas_feed" ? "Connecting…" : "Connect"}
                    </AppButton>
                  </div>
                  <div className="mt-2 text-[0.7rem] text-[var(--muted)]">
                    Honest limits: the feed can&apos;t tell what you&apos;ve already submitted, and it skips assignments with no due date.
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3">
              <span className={`size-2.5 rounded-full ${byId.prairielearn.connected ? "bg-[var(--success)]" : "bg-[var(--muted-light)]"}`} />
              <div>
                <div className="font-bold">PrairieLearn</div>
                <div className="text-xs text-[var(--muted)]">{byId.prairielearn.connected ? "Connected" : "Not connected"} &middot; {byId.prairielearn.detail}</div>
              </div>
            </div>
            {isLocalMode() && !sampleMode && (
              <AppButton disabled={busy !== null} onClick={() => run("prairielearn", connectPrairieLearn)} className="toggle-pill">
                {busy === "prairielearn" ? "Signing in…" : byId.prairielearn.connected ? "Reconnect" : "Connect"}
              </AppButton>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3">
              <span className={`size-2.5 rounded-full ${byId.prairielearn_ok.connected ? "bg-[var(--success)]" : "bg-[var(--muted-light)]"}`} />
              <div>
                <div className="font-bold">PrairieLearn (Okanagan)</div>
                <div className="text-xs text-[var(--muted)]">{byId.prairielearn_ok.connected ? "Connected" : "Not connected"} &middot; {byId.prairielearn_ok.detail}</div>
              </div>
            </div>
            {isLocalMode() && !sampleMode && (
              <AppButton disabled={busy !== null} onClick={() => run("prairielearn_ok", connectPrairieLearnOk)} className="toggle-pill">
                {busy === "prairielearn_ok" ? "Signing in…" : byId.prairielearn_ok.connected ? "Reconnect" : "Connect"}
              </AppButton>
            )}
          </div>

          {customConnections.map((c) => (
            <div key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="flex items-center gap-3">
                <span className="size-2.5 rounded-full bg-[var(--success)]" />
                <div>
                  <div className="font-bold">{c.label}</div>
                  <div className="text-xs text-[var(--muted)]">Connected &middot; {c.detail}</div>
                </div>
              </div>
              {isLocalMode() && !sampleMode && (
                <AppButton disabled={busy !== null} onClick={() => run(c.id, () => connectPrairieLearnCustom(`https://${c.id}`))} className="toggle-pill">
                  {busy === c.id ? "Signing in…" : "Reconnect"}
                </AppButton>
              )}
            </div>
          ))}

          {isLocalMode() && !sampleMode && (
            <div className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div className="flex items-center gap-3">
                <span className="size-2.5 rounded-full bg-[var(--muted-light)]" />
                <div>
                  <div className="font-bold">Different PrairieLearn?</div>
                  <div className="text-xs text-[var(--muted)]">Any school can self-host their own - paste its address (e.g. https://prairielearn.example.edu)</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="https://prairielearn.example.edu"
                  aria-label="Custom PrairieLearn URL"
                  className="w-56 rounded-md border border-[var(--line)] bg-[var(--surface-soft)] px-2 py-1 text-xs"
                />
                <AppButton disabled={busy !== null || !customDomain} onClick={() => run("prairielearn_custom", () => connectPrairieLearnCustom(customDomain))} className="toggle-pill">
                  {busy === "prairielearn_custom" ? "Signing in…" : "Connect"}
                </AppButton>
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3">
              <span className={`size-2.5 rounded-full ${byId.workday.connected ? "bg-[var(--success)]" : "bg-[var(--muted-light)]"}`} />
              <div>
                <div className="font-bold">Workday</div>
                <div className="text-xs text-[var(--muted)]">{byId.workday.connected ? "Loaded" : "Not loaded"} &middot; {byId.workday.detail}</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="text" value={term} onChange={(e) => setTerm(e.target.value)} size={7} aria-label="Term" className="rounded-md border border-[var(--line)] bg-[var(--surface-soft)] px-2 py-1 text-xs" />
              <label className="toggle-pill cursor-pointer">
                Import .xlsx
                <input type="file" accept=".xlsx" onChange={handleFile} className="sr-only" />
              </label>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 py-3">
            <div className="flex items-center gap-3">
              <span className="size-2.5 rounded-full bg-[var(--muted-light)]" />
              <div>
                <div className="font-bold">Bookstore</div>
                <div className="text-xs text-[var(--muted)]">The Bookstore lists the books for your courses after you sign in with CWL.</div>
              </div>
            </div>
            <a href="https://the.bookstore.ubc.ca/books/personalize-my-book-list-using-cwl" target="_blank" rel="noopener noreferrer" className="toggle-pill">
              Your textbooks →
            </a>
          </div>
        </div>
        {isLocalMode() && sampleMode && (
          <div className="mt-3 text-xs text-[var(--muted)]">Turn off Sample data above to connect a real Canvas or PrairieLearn account.</div>
        )}
        {workdayStatus && <div className="mt-3 text-xs text-[var(--muted)]">{workdayStatus}</div>}
        {error && <div className="connect-error mt-3">{error}</div>}
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
        <div className="mb-1 text-xl font-bold tracking-tight">Advanced: real Canvas / PrairieLearn login</div>
        <div className="mb-5 text-sm text-[var(--muted)]">
          This uses Playwright to open a real browser window on <strong className="text-[var(--ink)]">your own machine</strong> so you log in yourself - no website, including this one, can install software or open a browser for you. That has to run from a terminal.
        </div>
        <div className="mb-4 rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
          <div className="mb-2 text-xs font-bold text-[var(--muted)]">
            {isLocalMode() ? "✓ Detected: this page is running locally right now." : "One-liner, in a terminal (needs Homebrew's uv, nothing else - no repo clone):"}
          </div>
          {!isLocalMode() && (
            <>
              <pre className="overflow-x-auto rounded-md bg-[var(--surface)] p-3 text-[0.7rem] leading-relaxed">
{`curl -fsSL https://raw.githubusercontent.com/terraceonhigh/helloHacks26/main/tools/sync.sh | bash`}
              </pre>
              <div className="mt-2 text-[0.7rem] text-[var(--muted)]">
                Opens a browser window per provider for you to log into, scans Canvas and PrairieLearn, then prints a sync key - paste that into "Paste your hub sync key" above to see it here, same as the extension.
              </div>
            </>
          )}
        </div>
        {isLocalMode() && (
          <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-soft)] p-4">
            <div className="mb-2 text-sm font-bold">Push what you just logged into onto your hosted dashboard</div>
            <div className="mb-3 text-xs text-[var(--muted)]">
              Connect Canvas/PrairieLearn above first, then send those real items to your hosted hub (the same sync key the extension popup shows) so they show up everywhere, not just here.
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="url"
                value={pushBase}
                onChange={(e) => setPushBase(e.target.value)}
                placeholder="https://your-hub.vercel.app"
                aria-label="Hosted hub URL"
                className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-xs"
              />
              <input
                type="text"
                value={pushKeyInput}
                onChange={(e) => setPushKeyInput(e.target.value)}
                placeholder="Sync key from the extension"
                aria-label="Sync key to push with"
                className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-xs"
              />
              <AppButton
                disabled={busy !== null || !pushKeyInput || !pushBase || allItems.length === 0}
                onClick={() => run("push", async () => {
                  const stored = await pushToHostedStore(pushBase.replace(/\/$/, ""), pushKeyInput.trim(), allItems, allCoursesForPush);
                  setPushStatus(`Pushed ${stored} item${stored === 1 ? "" : "s"}.`);
                })}
                className="toggle-pill"
              >
                {busy === "push" ? "Pushing…" : "Push now"}
              </AppButton>
            </div>
            {allItems.length === 0 && <div className="mt-2 text-[0.7rem] text-[var(--muted)]">Nothing real loaded yet - connect Canvas or PrairieLearn above first.</div>}
            {pushStatus && <div className="mt-2 text-[0.7rem] text-[var(--muted)]">{pushStatus}</div>}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-6 shadow-[var(--shadow-card)]">
        <div className="mb-1 text-xl font-bold tracking-tight">Courses</div>
        <div className="mb-5 text-sm text-[var(--muted)]">
          Hide old or inactive courses a provider still lists (Canvas, especially, likes to keep listing ones you're not really in this term) - a hidden course disappears everywhere, not just here.
        </div>
        <div className="divide-y divide-[var(--line)]">
          {allCourses.map((c) => (
            <label key={c.code} className="flex cursor-pointer items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="font-bold">{c.code}</div>
                <div className="truncate text-xs text-[var(--muted)]">{c.title}</div>
              </div>
              <input
                type="checkbox"
                checked={!hiddenCourses.includes(c.code)}
                onChange={(e) => onToggleCourseHidden(c.code, e.target.checked)}
                aria-label={`Show ${c.code}`}
              />
            </label>
          ))}
          {allCourses.length === 0 && <div className="py-3 text-sm text-[var(--muted)]">No courses yet.</div>}
        </div>
      </section>
    </div>
  );
}

export default function App() {
  const [activeNav, setActiveNav] = useState("Overview");
  const [activeFilter, setActiveFilter] = useState("All");
  const [courseMenuOpen, setCourseMenuOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [hideOverdue, setHideOverdue] = useState(false);
  const [showN, setShowN] = useState(10);
  const [theme, setTheme] = useState("everforest");
  const [customColors, setCustomColors] = useState(DEFAULT_CUSTOM_COLORS);
  const [preferredKinds, setPreferredKinds] = useState(new Set());

  // First-time default: off in local mode (a local run means someone's about
  // to connect a real account, so show that path immediately rather than
  // hiding it behind fake data - matches the hosted demo, where real data
  // shows immediately) - on everywhere else, matching app.py's
  // st.toggle(value=True). Overridden below by whatever was saved last.
  const [sampleMode, setSampleMode] = useState(!isLocalMode());
  const [items, setItems] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [fetchedCourses, setFetchedCourses] = useState([]);
  const [meetings, setMeetings] = useState([]);
  const [demoMeetings, setDemoMeetings] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [hiddenCourses, setHiddenCourses] = useState([]);
  const [manuallyDoneKeys, setManuallyDoneKeys] = useState([]);
  const [feedConnected, setFeedConnected] = useState(false);
  const [feedItems, setFeedItems] = useState([]);
  const [feedError, setFeedError] = useState(null);
  const [storeItems, setStoreItems] = useState([]);
  const [storeCourses, setStoreCourses] = useState([]);
  const loadRequestId = useRef(0);
  const feedRequestId = useRef(0);

  useEffect(() => {
    setTheme(localStorage.getItem("gather-theme") || "everforest");
    try {
      const saved = JSON.parse(localStorage.getItem("gather-custom-colors"));
      if (saved) setCustomColors(saved);
    } catch {
      // ignore malformed/missing storage - keep the default
    }
    // Once the student has actually chosen (either way), that choice sticks
    // across reloads - so a real connection doesn't silently revert to fake
    // data, and so someone who deliberately wants sample data in local mode
    // keeps seeing it.
    const savedSampleMode = localStorage.getItem("gather-sample-mode");
    if (savedSampleMode !== null) setSampleMode(savedSampleMode === "true");
    try {
      const saved = JSON.parse(localStorage.getItem("gather-hidden-courses"));
      if (Array.isArray(saved)) setHiddenCourses(saved);
    } catch {
      // ignore malformed/missing storage - keep the default (nothing hidden)
    }
    try {
      // A student's own "I did this" checkbox (#98) - purely local, never
      // sent anywhere, and never changes what Canvas/PrairieLearn/Workday
      // themselves think happened.
      const saved = JSON.parse(localStorage.getItem("gather-manually-done"));
      if (Array.isArray(saved)) setManuallyDoneKeys(saved);
    } catch {
      // ignore malformed/missing storage - keep the default (nothing checked off)
    }
    setPreferredKinds(readPreferredKindsCookie());
    // The feed URL is a secret (works like a password): it lives only in an
    // httpOnly cookie the page can't read (see hub/ics.py's feed_request()).
    // An older build kept it in localStorage - migrate that once, deleting
    // it whatever happens, then refresh from the cookie on every load so a
    // saved connection keeps working without re-pasting the link.
    const requestId = ++feedRequestId.current;
    migrateLegacyFeedUrl(window.localStorage)
      .then(() => refreshCanvasFeed())
      .then((nextFeedItems) => {
        if (requestId !== feedRequestId.current) return; // superseded by a connect/disconnect since
        setFeedConnected(nextFeedItems !== null);
        setFeedItems(nextFeedItems ?? []);
      })
      .catch(() => {
        if (requestId !== feedRequestId.current) return;
        // Generic message only - a server error must never put the feed URL (a secret) on screen.
        setFeedConnected(true);
        setFeedError("Couldn't refresh your feed - it may have expired or changed.");
      });
    // Hosted store: a #sync=<key> link from the extension becomes an
    // httpOnly cookie, and the fragment is dropped from the address bar
    // before anything else happens. Any failure (503 until the store is
    // provisioned, 401 with no session) silently leaves the dashboard as is.
    if (!isLocalMode()) {
      const syncKey = syncKeyFromHash(window.location.hash);
      if (syncKey) {
        history.replaceState(null, "", window.location.pathname + window.location.search);
        connectHostedStore(syncKey).catch(() => {});
      } else {
        fetchHostedStore().then(applyHostedStore).catch(() => {});
      }
    }
  }, []);

  function togglePreferredKind(kindId) {
    setPreferredKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kindId)) next.delete(kindId);
      else next.add(kindId);
      writePreferredKindsCookie(next);
      return next;
    });
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("gather-theme", theme);
  }, [theme]);
  useEffect(() => {
    localStorage.setItem("gather-custom-colors", JSON.stringify(customColors));
  }, [customColors]);
  useEffect(() => {
    localStorage.setItem("gather-sample-mode", String(sampleMode));
  }, [sampleMode]);
  useEffect(() => {
    localStorage.setItem("gather-hidden-courses", JSON.stringify(hiddenCourses));
  }, [hiddenCourses]);
  useEffect(() => {
    localStorage.setItem("gather-manually-done", JSON.stringify(manuallyDoneKeys));
  }, [manuallyDoneKeys]);

  function toggleCourseHidden(code, visible) {
    setHiddenCourses((prev) => (visible ? prev.filter((c) => c !== code) : [...prev, code]));
  }

  function toggleItemDone(item) {
    const key = itemKey(item);
    setManuallyDoneKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }

  async function connectCanvasFeed(url) {
    const requestId = ++feedRequestId.current;
    let nextFeedItems;
    try {
      nextFeedItems = await postCanvasFeed(url);
    } catch {
      // Generic message only - a server error must never put the feed URL (a secret) on screen.
      throw new Error("Couldn't load that feed - double check the link and try again.");
    }
    if (requestId !== feedRequestId.current) return; // superseded by a disconnect/another connect since
    setFeedConnected(true); // the URL itself is now only in the httpOnly cookie
    setFeedItems(nextFeedItems);
    setFeedError(null);
  }

  function disconnectCanvasFeed() {
    feedRequestId.current++; // invalidate any in-flight fetch, so it can't overwrite this afterward
    setFeedConnected(false);
    setFeedItems([]);
    setFeedError(null);
    deleteCanvasFeed(); // the server clears the cookie
  }

  async function load(useSample) {
    // A slow local-mode response can land after the student has already
    // flipped back to Sample (or vice versa) - a sequence number, not just
    // "latest wins by promise order", so a stale response is dropped instead
    // of overwriting what's now on screen with a mismatched useSample's data.
    const requestId = ++loadRequestId.current;
    try {
      const [nextItems, nextCourses] = await Promise.all([fetchUpcoming(useSample), fetchCourses(useSample)]);
      if (requestId !== loadRequestId.current) return;
      setItems(nextItems);
      setFetchedCourses(nextCourses);
      setLoadError(null);
    } catch (e) {
      if (requestId !== loadRequestId.current) return;
      setItems([]);
      setFetchedCourses([]);
      setLoadError(e.message);
    }
    // Announcements are a separate, best-effort feed (GET /api/announcements
    // isn't on every backend yet - e.g. before #50 merges) - a missing or
    // failing endpoint shouldn't take the rest of the dashboard down with it
    // the way a failed items/courses fetch does.
    try {
      setAnnouncements(await fetchAnnouncements(useSample));
    } catch {
      setAnnouncements([]);
    }
    // The demo student's class meetings (hosted Sample mode; [] otherwise).
    // Kept apart from `meetings` (the student's own Workday import) so they
    // never count as a real connection and vanish when Sample goes off.
    const nextDemoMeetings = await fetchDemoMeetings(useSample);
    if (requestId === loadRequestId.current) setDemoMeetings(nextDemoMeetings);
  }

  function importWorkdaySchedule(imported) {
    setMeetings((prev) => mergeMeetings(prev, imported));
  }

  function applyHostedStore(store) {
    if (!store) return false;
    setStoreItems(store.items);
    setStoreCourses(store.courses);
    // A real sync means there's real data to show - don't make the student
    // also find and flip the Sample data toggle themselves.
    const hasData = store.items.length > 0 || store.courses.length > 0;
    if (hasData) setSampleMode(false);
    return hasData;
  }

  async function connectHostedStore(key) {
    const ok = await startHostedSession(key);
    if (!ok) throw new Error("That sync key wasn't accepted.");
    return applyHostedStore(await fetchHostedStore());
  }

  useEffect(() => {
    load(sampleMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sampleMode]);

  const now = new Date();
  const allCourses = mergeCourses(fetchedCourses, storeCourses);
  const courses = selectVisibleCourses(allCourses, hiddenCourses);
  const allItems = mergeItems(mergeItems(items, storeItems), feedItems);
  const activeItems = hideCourseItems(selectActiveItems(allItems, manuallyDoneKeys), hiddenCourses);
  const doneCount = hideCourseItems(allItems, hiddenCourses).filter((item) => isDone(item, manuallyDoneKeys)).length;
  const overdueCount = activeItems.filter((item) => isOverdue(item, now)).length;
  const dueThisWeekCount = activeItems.filter((item) => {
    if (!item.due) return false;
    const hours = (new Date(item.due) - now) / 3_600_000;
    return hours <= 24 * 7;
  }).length;

  const activeNavTab = NAV_ITEMS.find((n) => n.label === activeNav)?.tab ?? "all";

  const searched = useMemo(() => {
    const term = search.toLowerCase();
    if (!term) return activeItems;
    return activeItems.filter((item) => item.title.toLowerCase().includes(term) || item.course.toLowerCase().includes(term));
  }, [activeItems, search]);

  const filteredByCourse = activeFilter === "All" ? searched : searched.filter((item) => item.course === activeFilter);
  const visible = selectVisibleItems(filteredByCourse, { tab: activeNavTab, hideOverdue, showN, now, preferredKinds });

  const searchedAnnouncements = useMemo(() => {
    const visibleAnnouncementsBase = hideCourseItems(announcements, hiddenCourses);
    const term = search.toLowerCase();
    if (!term) return visibleAnnouncementsBase;
    return visibleAnnouncementsBase.filter((item) => item.title.toLowerCase().includes(term) || item.course.toLowerCase().includes(term));
  }, [announcements, hiddenCourses, search]);
  const visibleAnnouncements = (activeFilter === "All" ? searchedAnnouncements : searchedAnnouncements.filter((item) => item.course === activeFilter)).slice(0, showN);

  const topAssignments = selectVisibleItems(activeItems, { tab: "all", hideOverdue: false, showN: 5, now, preferredKinds });
  const nextUp = selectNextUp(activeItems, preferredKinds);
  const days = weekDates(now);
  // Sample/demo rows now carry a real `source` (the hosted demo runs the real
  // adapters over a fake student), but nothing is actually connected - so
  // outside local live mode only the hosted store's and the feed's items
  // count toward Settings' Connections, never the sample/demo `items`.
  const connectedItems = isLocalMode() && !sampleMode ? allItems : mergeItems(storeItems, feedItems);
  const connections = selectConnections(connectedItems, meetings);
  const shownMeetings = mergeMeetings(demoMeetings, meetings);

  const customStyle = theme === "custom"
    ? { "--page": customColors.page, "--surface": customColors.surface, "--ink": customColors.ink, "--accent": customColors.accent }
    : undefined;

  return (
    <div data-theme={theme} style={customStyle} className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <div className="flex h-full flex-col">
          <div className="flex-1 overflow-y-auto">
            <div className="flex items-center gap-3 px-6 py-7">
              <div className="logo-mark"><span /><span /><span /></div>
              <div className="text-xl font-bold tracking-tight">Lauds</div>
            </div>

            <nav className="mt-4 flex flex-col gap-1 px-3">
              {NAV_ITEMS.map((item) => (
                <AppButton key={item.label} onClick={() => { setActiveNav(item.label); setMobileNav(false); }} className={`nav-item ${activeNav === item.label ? "nav-item-active" : ""}`}>
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </AppButton>
              ))}
            </nav>

            <div className="mx-5 my-7 h-px bg-[var(--line)]" />
            <div className="px-6 text-xs font-bold uppercase tracking-widest text-[var(--muted)]">Courses</div>
            <div className="mt-4 flex flex-col gap-1 px-3">
              {courses.map((course) => (
                <AppButton key={course.code} onClick={() => { setActiveFilter(course.code); setMobileNav(false); }} className={`course-nav ${activeFilter === course.code ? "nav-item-active" : ""}`}>
                  <span className="course-nav-mark">{course.code.slice(0, 2)}</span>
                  <span className="min-w-0 flex-1 truncate text-left">{course.code}</span>
                  <span className="text-xs font-bold text-[var(--muted)]">{selectCourseItems(activeItems, course.code).length}</span>
                </AppButton>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3 border-t border-[var(--line)] px-4 py-4">
            <div className="avatar">SD</div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-bold">Stu Dent</div>
              <div className="truncate text-xs text-[var(--muted)]">Student</div>
            </div>
            <AppButton
              ariaLabel="Settings"
              onClick={() => { setActiveNav("Settings"); setMobileNav(false); }}
              className={`icon-button gap-1.5 px-2 ${activeNav === "Settings" ? "nav-item-active" : ""}`}
            >
              <Icon name="settings" className="size-4" />
              <span className="text-xs font-bold">Settings</span>
            </AppButton>
          </div>
        </div>
      </aside>

      {mobileNav && <div className="fixed inset-0 z-30 bg-black/20 lg:hidden" onClick={() => setMobileNav(false)} />}

      <main className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-20 items-center gap-4 border-b border-[var(--line)] bg-[color:var(--page-glass)] px-5 backdrop-blur-xl sm:px-8 lg:px-10">
          <AppButton ariaLabel="Open menu" onClick={() => setMobileNav(true)} className="icon-button lg:hidden"><Icon name="menu" /></AppButton>
          <div className="search-shell">
            <Icon name="search" className="size-5 text-[var(--muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search assignments" placeholder="Search assignments, courses..." className="search-input" />
          </div>
        </header>

        <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
          {activeNav === "Settings" ? (
            <SettingsPage
              theme={theme}
              setTheme={setTheme}
              customColors={customColors}
              setCustomColors={setCustomColors}
              connections={connections}
              sampleMode={sampleMode}
              onSampleModeChange={setSampleMode}
              onConnected={() => load(false)}
              onScheduleImported={importWorkdaySchedule}
              allCourses={allCourses}
              hiddenCourses={hiddenCourses}
              onToggleCourseHidden={toggleCourseHidden}
              feedConnected={feedConnected}
              feedItemCount={feedItems.length}
              feedError={feedError}
              onConnectFeed={connectCanvasFeed}
              onDisconnectFeed={disconnectCanvasFeed}
              preferredKinds={preferredKinds}
              onTogglePreferredKind={togglePreferredKind}
              onConnectHosted={connectHostedStore}
              onSynced={async () => applyHostedStore(await fetchHostedStore())}
              hostedConnected={storeItems.length > 0 || storeCourses.length > 0}
              allItems={allItems}
              allCoursesForPush={allCourses}
            />
          ) : activeNav === "Schedule" ? (
            <section className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-card)]">
              <div className="border-b border-[var(--line)] p-5 sm:p-6">
                <div className="text-xl font-bold tracking-tight">Weekly schedule</div>
                <div className="mt-1 text-sm text-[var(--muted)]">Your recurring class meetings, from Workday</div>
              </div>
              <ScheduleView meetings={shownMeetings} now={now} />
            </section>
          ) : (
          <>
          <section className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-bold text-[var(--accent)]">
                {now.toLocaleDateString("en-CA", { weekday: "long", month: "long", day: "numeric" })}
              </div>
              <div className="text-3xl font-bold tracking-tight sm:text-4xl">
                {sampleMode ? "Sample data" : "Your dashboard"}
              </div>
              <div className="mt-2 text-[var(--muted)]">
                <strong className="font-bold text-[var(--ink)]">{dueThisWeekCount} item{dueThisWeekCount === 1 ? "" : "s"}</strong> due in the next 7 days.
              </div>
            </div>
          </section>

          {loadError && <p className="connect-error mb-4">Couldn&apos;t load: {loadError}</p>}

          {activeNav !== "Calendar" && (
            <section className="mb-8 grid gap-4 sm:grid-cols-3">
              <div className="stat-card stat-card-featured">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold text-white/70">Due this week</div>
                    <div className="mt-3 text-4xl font-bold tracking-tight">{dueThisWeekCount}</div>
                  </div>
                  <div className="rounded-xl bg-white/10 p-2.5"><Icon name="tasks" /></div>
                </div>
              </div>
              <div className="stat-card">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[var(--muted)]">Completed</div>
                    <div className="mt-3 text-4xl font-bold tracking-tight">{doneCount}</div>
                  </div>
                  <div className="rounded-xl bg-[var(--success-soft)] p-2.5 text-[var(--success)]"><Icon name="check" /></div>
                </div>
              </div>
              <div className="stat-card">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[var(--muted)]">Overdue</div>
                    <div className="mt-3 text-4xl font-bold tracking-tight">{overdueCount}</div>
                  </div>
                  <div className="rounded-xl bg-[var(--danger-soft)] p-2.5 text-[var(--danger)]"><Icon name="clock" /></div>
                </div>
              </div>
            </section>
          )}

          <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
            <section className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-card)]">
              {activeNav === "Overview" ? (
                <>
                  <div className="flex items-center justify-between gap-4 border-b border-[var(--line)] p-5 sm:p-6">
                    <div>
                      <div className="text-xl font-bold tracking-tight">Top assignments</div>
                      <div className="mt-1 text-sm text-[var(--muted)]">Your {topAssignments.length} most urgent, across every platform</div>
                    </div>
                    <AppButton onClick={() => setActiveNav("Assignments")} className="filter-button">View all</AppButton>
                  </div>
                  <div>
                    {topAssignments.map((item) => (
                      <div key={item.id} className="assignment-row">
                        <input
                          type="checkbox"
                          aria-label={`Mark "${item.title}" as done`}
                          onChange={() => toggleItemDone(item)}
                          className="size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                        />
                        <span className="course-mark">{item.course.slice(0, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">
                            {item.title}
                            {preferredKinds.has(item.kind) && <span className="due-soon ml-2 rounded-md px-1.5 py-0.5 text-[0.65rem] font-bold align-middle">Priority</span>}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-[var(--muted)]">
                            <span>{item.course}</span><span>·</span><span>{item.kind}</span>
                            {/* The boxed due-date badge below is sm:+ only - repeat it as
                                plain text here so due dates aren't lost below that breakpoint. */}
                            <span className={`sm:hidden ${isOverdue(item, now) ? "font-bold text-[var(--danger)]" : ""}`}>· {formatDue(item.due)}</span>
                          </div>
                        </div>
                        <div className={`hidden shrink-0 rounded-lg px-3 py-2 text-right sm:block ${isOverdue(item, now) ? "due-now" : ""}`}>
                          <div className="text-xs font-bold">{formatDue(item.due)}</div>
                          <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{displayLabel(item.urgency)}</div>
                        </div>
                        <a href={item.url} aria-label="Open"><Icon name="arrow" className="size-4 shrink-0 text-[var(--muted-light)]" /></a>
                      </div>
                    ))}
                    {topAssignments.length === 0 && (
                      <div className="p-10 text-center text-sm text-[var(--muted)]">
                        {sampleMode ? "Nothing upcoming." : "Nothing yet. Connect Canvas or PrairieLearn in Settings."}
                      </div>
                    )}
                  </div>
                </>
              ) : activeNav === "Calendar" ? (
                <CalendarSection items={activeItems} meetings={shownMeetings} now={now} onToggleItemDone={toggleItemDone} />
              ) : (
              <>
              <div className="flex flex-col gap-4 border-b border-[var(--line)] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                <div>
                  <div className="text-xl font-bold tracking-tight">
                    {activeNavTab === "courses" ? "Courses" : activeNavTab === "announcements" ? "Announcements" : "Upcoming assignments"}
                  </div>
                  <div className="mt-1 text-sm text-[var(--muted)]">Everything due across your connected platforms</div>
                </div>
                <div className="relative shrink-0">
                  <AppButton
                    onClick={() => setCourseMenuOpen((open) => !open)}
                    ariaLabel="Filter courses"
                    className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-xs font-bold"
                  >
                    <span>{activeFilter === "All" ? "All courses" : activeFilter}</span>
                    <Icon name="arrow" className="size-3 rotate-90" />
                  </AppButton>
                  {courseMenuOpen && (
                    <div className="absolute right-0 top-[calc(100%+8px)] z-10 w-48 rounded-xl border border-[var(--line)] bg-[var(--surface)] p-1.5 shadow-[var(--shadow-card)]">
                      {[{ id: "All", label: "All courses" }, ...courses.map((c) => ({ id: c.code, label: c.code }))].map((filter) => (
                        <label key={filter.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-semibold hover:bg-[var(--surface-soft)]">
                          <input
                            type="checkbox"
                            checked={activeFilter === filter.id}
                            onChange={() => { setActiveFilter(filter.id); setCourseMenuOpen(false); }}
                          />
                          <span>{filter.label}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-4 border-b border-[var(--line)] px-5 py-3 text-sm sm:px-6">
                <label>
                  Show next{" "}
                  <input type="range" min={5} max={50} value={showN} onChange={(e) => setShowN(Number(e.target.value))} />{" "}
                  {showN}
                </label>
                {activeNavTab !== "announcements" && (
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={hideOverdue} onChange={(e) => setHideOverdue(e.target.checked)} />
                    Hide overdue
                  </label>
                )}
              </div>

              <div>
                {activeNavTab === "announcements" ? (
                  visibleAnnouncements.length === 0 ? (
                    <div className="p-10 text-center text-sm text-[var(--muted)]">
                      {sampleMode ? "No announcements in sample data." : "Nothing yet. Connect Canvas in Settings."}
                    </div>
                  ) : (
                    visibleAnnouncements.map((item) => (
                      <div key={item.id} className="assignment-row">
                        <span className="course-mark">{item.course.slice(0, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">{item.title}</div>
                          <div className="mt-1 text-xs font-medium text-[var(--muted)]">{item.course}</div>
                        </div>
                        <a href={item.url} aria-label="Open"><Icon name="arrow" className="size-4 shrink-0 text-[var(--muted-light)]" /></a>
                      </div>
                    ))
                  )
                ) : activeNavTab === "courses" ? (
                  courses.length === 0 ? (
                    <div className="p-10 text-center text-sm text-[var(--muted)]">
                      {sampleMode ? "No courses." : "Nothing yet. Connect Canvas in Settings."}
                    </div>
                  ) : (
                    courses.map((course) => (
                      <div key={course.code} className="border-b border-[var(--line)] p-5 last:border-b-0">
                        <div className="mb-1 font-bold">
                          {course.code} <span className="font-normal text-[var(--muted)]">{course.title}</span>
                        </div>
                        <div className="mb-3 text-xs text-[var(--muted)]">
                          {course.term} &middot; Grade: {course.grade == null ? "—" : `${course.grade}%`}
                        </div>
                        {selectCourseItems(activeItems, course.code, preferredKinds).map((item) => (
                          <div key={item.id} className={`assignment-row ${isOverdue(item, now) ? "due-now" : ""}`}>
                            <input
                              type="checkbox"
                              aria-label={`Mark "${item.title}" as done`}
                              onChange={() => toggleItemDone(item)}
                              className="size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                            />
                            <span className="course-mark">{item.course.slice(0, 2)}</span>
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-bold">
                                {item.title}
                                {preferredKinds.has(item.kind) && <span className="due-soon ml-2 rounded-md px-1.5 py-0.5 text-[0.65rem] font-bold align-middle">Priority</span>}
                              </div>
                              <div className="text-xs text-[var(--muted)]">{item.kind} &middot; {displayLabel(item.urgency)} &middot; {formatDue(item.due)}</div>
                            </div>
                            <a href={item.url} className="text-xs font-bold text-[var(--accent)]">open</a>
                          </div>
                        ))}
                      </div>
                    ))
                  )
                ) : (
                  <>
                    {visible.map((item) => (
                      <div key={item.id} className="assignment-row">
                        <input
                          type="checkbox"
                          aria-label={`Mark "${item.title}" as done`}
                          onChange={() => toggleItemDone(item)}
                          className="size-4 shrink-0 cursor-pointer accent-[var(--accent)]"
                        />
                        <span className="course-mark">{item.course.slice(0, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">
                            {item.title}
                            {preferredKinds.has(item.kind) && <span className="due-soon ml-2 rounded-md px-1.5 py-0.5 text-[0.65rem] font-bold align-middle">Priority</span>}
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-[var(--muted)]">
                            <span>{item.course}</span><span>·</span><span>{item.kind}</span>
                            {/* The boxed due-date badge below is sm:+ only - repeat it as
                                plain text here so due dates aren't lost below that breakpoint. */}
                            <span className={`sm:hidden ${isOverdue(item, now) ? "font-bold text-[var(--danger)]" : ""}`}>· {formatDue(item.due)}</span>
                          </div>
                        </div>
                        <div className={`hidden shrink-0 rounded-lg px-3 py-2 text-right sm:block ${isOverdue(item, now) ? "due-now" : ""}`}>
                          <div className="text-xs font-bold">{formatDue(item.due)}</div>
                          <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{displayLabel(item.urgency)}</div>
                        </div>
                        <a href={item.url} aria-label="Open"><Icon name="arrow" className="size-4 shrink-0 text-[var(--muted-light)]" /></a>
                      </div>
                    ))}
                    {visible.length === 0 && (
                      <div className="p-10 text-center text-sm text-[var(--muted)]">
                        {sampleMode ? "Nothing upcoming." : "Nothing yet. Connect Canvas or PrairieLearn in Settings."}
                      </div>
                    )}
                  </>
                )}
              </div>
              </>
              )}
            </section>

            <aside className="space-y-5">
              <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
                <div className="mb-5 font-bold">This week</div>
                <div className="grid grid-cols-7 gap-1 text-center">
                  {WEEKDAY_LETTERS.map((day, index) => <div key={`${day}-${index}`} className="text-[0.65rem] font-bold text-[var(--muted)]">{day}</div>)}
                  {days.map((d) => (
                    <div key={d.toISOString()} className={`calendar-day ${d.toDateString() === now.toDateString() ? "calendar-day-active" : ""}`}>
                      <span>{d.getDate()}</span>
                      {hasItemDueOn(activeItems, d) && <span className={`size-1 rounded-full ${d.toDateString() === now.toDateString() ? "bg-white" : "bg-[var(--accent)]"}`} />}
                    </div>
                  ))}
                </div>
                {nextUp && (
                  <div className="mt-5 rounded-xl bg-[var(--surface-soft)] p-4">
                    <div className="text-xs font-bold uppercase tracking-wider text-[var(--muted)]">Next up</div>
                    <div className="mt-2 text-sm font-bold">{nextUp.title}</div>
                    <div className="mt-1 flex items-center gap-1.5 text-xs text-[var(--muted)]"><Icon name="clock" className="size-3.5" /> {formatDue(nextUp.due)}</div>
                  </div>
                )}
              </section>

              <AppButton onClick={() => setActiveNav("Settings")} className="toggle-pill w-full justify-center">
                Manage connections in Settings
              </AppButton>
            </aside>
          </div>
          </>
          )}
        </div>
      </main>
    </div>
  );
}
