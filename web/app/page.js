"use client";

import { useEffect, useMemo, useState } from "react";
import {
  connectCanvas,
  connectPrairieLearn,
  displayLabel,
  fetchCourses,
  fetchUpcoming,
  formatDue,
  hasItemDueOn,
  isDone,
  isLocalMode,
  isOverdue,
  mergeCourses,
  monthGrid,
  selectActiveItems,
  selectConnections,
  selectCourseItems,
  selectItemsDueOn,
  selectNextUp,
  selectVisibleItems,
  weekDates,
} from "../lib/hub";
import { parseWorkdayCourses } from "../lib/workday";

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
    spark: <><path d="m12 3 1.3 4.2L17 9l-3.7 1.8L12 15l-1.3-4.2L7 9l3.7-1.8L12 3Z" /><path d="m5 14 .7 2.3L8 17l-2.3.7L5 20l-.7-2.3L2 17l2.3-.7L5 14Z" /></>,
    settings: <><path d="M4 6h10M18 6h2M4 18h10M18 18h2M4 12h4M12 12h8" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="16" cy="18" r="2" /></>,
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
  { label: "Courses", icon: "courses", tab: "courses" },
  { label: "Settings", icon: "settings", tab: "settings" },
];

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
const MONTH_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// The Calendar nav tab's own page: a month grid of every active item's due
// date, plus the clicked day's items below. Owns its own displayed-month and
// selected-day state rather than lifting it into App(), since nothing else
// in the app needs to know which day is selected here.
function CalendarSection({ items, now }) {
  const [monthDate, setMonthDate] = useState(new Date(now.getFullYear(), now.getMonth(), 1));
  const [selectedDay, setSelectedDay] = useState(null);

  const weeks = useMemo(() => monthGrid(monthDate), [monthDate]);
  const dayItems = useMemo(() => (selectedDay ? selectItemsDueOn(items, selectedDay) : []), [items, selectedDay]);

  function shiftMonth(delta) {
    setMonthDate((d) => new Date(d.getFullYear(), d.getMonth() + delta, 1));
    setSelectedDay(null);
  }

  function goToday() {
    setMonthDate(new Date(now.getFullYear(), now.getMonth(), 1));
    setSelectedDay(now);
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

      <div className="p-5 sm:p-6">
        <div className="grid grid-cols-7 gap-1 text-center">
          {MONTH_WEEKDAY_LABELS.map((label) => (
            <div key={label} className="pb-2 text-[0.65rem] font-bold text-[var(--muted)]">{label}</div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {weeks.flat().map(({ date, inMonth }) => {
            const dueCount = selectItemsDueOn(items, date).length;
            const isToday = date.toDateString() === now.toDateString();
            const isSelected = selectedDay && date.toDateString() === selectedDay.toDateString();
            return (
              <button
                key={date.toISOString()}
                aria-label={date.toDateString()}
                onClick={() => setSelectedDay(date)}
                className={`flex aspect-square flex-col items-center justify-center gap-1 rounded-lg border text-sm font-semibold transition-colors ${
                  isSelected ? "border-[var(--accent)] bg-[var(--accent-soft)]" : "border-transparent hover:bg-[var(--surface-soft)]"
                } ${inMonth ? "text-[var(--ink)]" : "text-[var(--muted-light)]"} ${isToday ? "text-[var(--accent)]" : ""}`}
              >
                <span>{date.getDate()}</span>
                {dueCount > 0 && <span className="size-1.5 rounded-full bg-[var(--accent)]" />}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className="border-t border-[var(--line)] px-5 py-3 text-sm font-bold sm:px-6">
          {selectedDay
            ? selectedDay.toLocaleDateString("en-CA", { weekday: "long", month: "long", day: "numeric" })
            : "Select a day to see what's due"}
        </div>
        {selectedDay && dayItems.map((item) => (
          <div key={item.id} className={`assignment-row ${isOverdue(item, now) ? "due-now" : ""}`}>
            <span className="course-mark">{item.course.slice(0, 2)}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-bold">{item.title}</div>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-[var(--muted)]">
                <span>{item.course}</span><span>·</span><span>{item.kind}</span>
              </div>
            </div>
            <div className="hidden shrink-0 rounded-lg px-3 py-2 text-right sm:block">
              <div className="text-xs font-bold">{formatDue(item.due)}</div>
              <div className="mt-0.5 text-[0.7rem] text-[var(--muted)]">{displayLabel(item.urgency)}</div>
            </div>
            <a href={item.url} aria-label="Open"><Icon name="arrow" className="size-4 shrink-0 text-[var(--muted-light)]" /></a>
          </div>
        ))}
        {selectedDay && dayItems.length === 0 && (
          <div className="p-10 text-center text-sm text-[var(--muted)]">Nothing due this day.</div>
        )}
      </div>
    </>
  );
}

function QuickActions({ sampleMode, onSampleModeChange, onConnected, onWorkdayImported }) {
  const [term, setTerm] = useState("2026W1");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  async function handleFile(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const buf = await file.arrayBuffer();
      const courses = parseWorkdayCourses(buf, term);
      onWorkdayImported(courses);
      setStatus(`Imported ${courses.length} course${courses.length === 1 ? "" : "s"}.`);
    } catch (err) {
      setStatus(null);
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
      setError(`${name}: ${e.message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 shadow-[var(--shadow-card)]">
      <div className="mb-4 font-bold">Quick actions</div>
      <label className="toggle-pill mb-3 flex w-full items-center justify-between">
        <span>Sample data</span>
        <input type="checkbox" checked={sampleMode} onChange={(e) => onSampleModeChange(e.target.checked)} />
      </label>
      {isLocalMode() && !sampleMode && (
        <div className="mb-3 flex flex-col gap-2">
          <AppButton disabled={busy !== null} onClick={() => run("canvas", connectCanvas)} className="toggle-pill justify-center">
            {busy === "canvas" ? "Signing in…" : "Connect Canvas"}
          </AppButton>
          <AppButton disabled={busy !== null} onClick={() => run("prairielearn", connectPrairieLearn)} className="toggle-pill justify-center">
            {busy === "prairielearn" ? "Signing in…" : "Connect PrairieLearn"}
          </AppButton>
        </div>
      )}
      <div className="flex items-center gap-2">
        <input type="text" value={term} onChange={(e) => setTerm(e.target.value)} size={7} className="rounded-md border border-[var(--line)] bg-[var(--surface-soft)] px-2 py-1 text-xs" />
        <label className="toggle-pill flex-1 justify-center text-center">
          Import Workday
          <input type="file" accept=".xlsx" onChange={handleFile} className="hidden" />
        </label>
      </div>
      {status && <div className="mt-2 text-xs text-[var(--muted)]">{status}</div>}
      {error && <div className="connect-error mt-2">{error}</div>}
    </section>
  );
}

function SettingsPage({ theme, setTheme, customColors, setCustomColors, connections }) {
  return (
    <div className="max-w-2xl space-y-6">
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
            : "This is the hosted demo, so Canvas and PrairieLearn can't connect here - run Hub locally to link a real account (see the README)."}
        </div>
        <div className="divide-y divide-[var(--line)]">
          {connections.map((c) => (
            <div key={c.id} className="flex items-center justify-between py-3">
              <div className="flex items-center gap-3">
                <span className={`size-2.5 rounded-full ${c.connected ? "bg-[var(--success)]" : "bg-[var(--muted-light)]"}`} />
                <span className="font-bold">{c.label}</span>
              </div>
              <div className="text-right text-sm">
                <div className={c.connected ? "font-bold text-[var(--success)]" : "text-[var(--muted)]"}>{c.connected ? "Connected" : "Not connected"}</div>
                <div className="text-xs text-[var(--muted)]">{c.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function App() {
  const [activeNav, setActiveNav] = useState("Overview");
  const [activeFilter, setActiveFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [hideOverdue, setHideOverdue] = useState(false);
  const [showN, setShowN] = useState(10);
  const [theme, setTheme] = useState("everforest");
  const [customColors, setCustomColors] = useState(DEFAULT_CUSTOM_COLORS);

  const [sampleMode, setSampleMode] = useState(true);
  const [items, setItems] = useState([]);
  const [fetchedCourses, setFetchedCourses] = useState([]);
  const [importedCourses, setImportedCourses] = useState([]);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    setTheme(localStorage.getItem("gather-theme") || "everforest");
    try {
      const saved = JSON.parse(localStorage.getItem("gather-custom-colors"));
      if (saved) setCustomColors(saved);
    } catch {
      // ignore malformed/missing storage - keep the default
    }
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("gather-theme", theme);
  }, [theme]);
  useEffect(() => {
    localStorage.setItem("gather-custom-colors", JSON.stringify(customColors));
  }, [customColors]);

  async function load(useSample) {
    try {
      const [nextItems, nextCourses] = await Promise.all([fetchUpcoming(useSample), fetchCourses(useSample)]);
      setItems(nextItems);
      setFetchedCourses(nextCourses);
      setLoadError(null);
    } catch (e) {
      setItems([]);
      setFetchedCourses([]);
      setLoadError(e.message);
    }
  }

  function importWorkdayCourses(imported) {
    setImportedCourses((prev) => mergeCourses(prev, imported));
  }

  useEffect(() => {
    load(sampleMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sampleMode]);

  const now = new Date();
  const courses = mergeCourses(fetchedCourses, importedCourses);
  const activeItems = selectActiveItems(items);
  const doneCount = items.filter(isDone).length;
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
  const visible = selectVisibleItems(filteredByCourse, { tab: activeNavTab, hideOverdue, showN, now });
  const topAssignments = selectVisibleItems(activeItems, { tab: "all", hideOverdue: false, showN: 5, now });
  const nextUp = selectNextUp(activeItems);
  const days = weekDates(now);
  const connections = selectConnections(items, importedCourses);

  const customStyle = theme === "custom"
    ? { "--page": customColors.page, "--surface": customColors.surface, "--ink": customColors.ink, "--accent": customColors.accent }
    : undefined;

  return (
    <div data-theme={theme} style={customStyle} className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <div className="flex h-full flex-col overflow-y-auto">
          <div className="flex items-center gap-3 px-6 py-7">
            <div className="logo-mark"><span /><span /><span /></div>
            <div className="text-xl font-bold tracking-tight">UBC Hub</div>
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
            <SettingsPage theme={theme} setTheme={setTheme} customColors={customColors} setCustomColors={setCustomColors} connections={connections} />
          ) : (
          <>
          <section className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
            <div>
              <div className="mb-2 flex items-center gap-2 text-sm font-bold text-[var(--accent)]">
                <Icon name="spark" className="size-4" />
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
                        <span className="course-mark">{item.course.slice(0, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">{item.title}</div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-[var(--muted)]">
                            <span>{item.course}</span><span>·</span><span>{item.kind}</span>
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
                        {sampleMode ? "Nothing upcoming." : "Nothing yet. Connect Canvas or PrairieLearn above."}
                      </div>
                    )}
                  </div>
                </>
              ) : activeNav === "Calendar" ? (
                <CalendarSection items={activeItems} now={now} />
              ) : (
              <>
              <div className="flex flex-col gap-4 border-b border-[var(--line)] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
                <div>
                  <div className="text-xl font-bold tracking-tight">{activeNavTab === "courses" ? "Courses" : "Upcoming assignments"}</div>
                  <div className="mt-1 text-sm text-[var(--muted)]">Everything due across your connected platforms</div>
                </div>
                <div className="flex max-w-full gap-1 overflow-x-auto rounded-xl bg-[var(--surface-soft)] p-1">
                  {[{ id: "All", label: "All courses" }, ...courses.map((c) => ({ id: c.code, label: c.code }))].map((filter) => (
                    <AppButton key={filter.id} onClick={() => setActiveFilter(filter.id)} className={`filter-button ${activeFilter === filter.id ? "filter-button-active" : ""}`}>{filter.label}</AppButton>
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-4 border-b border-[var(--line)] px-5 py-3 text-sm sm:px-6">
                <label>
                  Show next{" "}
                  <input type="range" min={5} max={50} value={showN} onChange={(e) => setShowN(Number(e.target.value))} />{" "}
                  {showN}
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={hideOverdue} onChange={(e) => setHideOverdue(e.target.checked)} />
                  Hide overdue
                </label>
              </div>

              <div>
                {activeNavTab === "courses" ? (
                  courses.length === 0 ? (
                    <div className="p-10 text-center text-sm text-[var(--muted)]">
                      {sampleMode ? "No courses." : "Nothing yet. Connect Canvas above."}
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
                        {selectCourseItems(activeItems, course.code).map((item) => (
                          <div key={item.id} className={`assignment-row ${isOverdue(item, now) ? "due-now" : ""}`}>
                            <span className="course-mark">{item.course.slice(0, 2)}</span>
                            <div className="min-w-0 flex-1">
                              <div className="truncate font-bold">{item.title}</div>
                              <div className="text-xs text-[var(--muted)]">{displayLabel(item.urgency)} &middot; {formatDue(item.due)}</div>
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
                        <span className="course-mark">{item.course.slice(0, 2)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-bold">{item.title}</div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-[var(--muted)]">
                            <span>{item.course}</span><span>·</span><span>{item.kind}</span>
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
                        {sampleMode ? "Nothing upcoming." : "Nothing yet. Connect Canvas or PrairieLearn above."}
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

              <QuickActions
                sampleMode={sampleMode}
                onSampleModeChange={setSampleMode}
                onConnected={() => load(false)}
                onWorkdayImported={importWorkdayCourses}
              />
            </aside>
          </div>
          </>
          )}
        </div>
      </main>
    </div>
  );
}
