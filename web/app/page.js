"use client";

import { useEffect, useState } from "react";
import {
  connectCanvas,
  connectPrairieLearn,
  displayLabel,
  fetchCourses,
  fetchUpcoming,
  isDone,
  isLocalMode,
  isOverdue,
  sortItems,
} from "../lib/hub";
import { parseWorkdayCourses } from "../lib/workday";

const TABS = [
  { key: "all", label: "All" },
  { key: "task", label: "Tasks" },
  { key: "deadline", label: "Deadlines" },
  { key: "material", label: "Materials" },
  { key: "courses", label: "Courses" },
];

function formatDue(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function ConnectBar({ onConnected }) {
  const [busy, setBusy] = useState(null); // "canvas" | "prairielearn" | null
  const [error, setError] = useState(null);

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
    <div className="connect-bar">
      <button disabled={busy !== null} onClick={() => run("canvas", connectCanvas)}>
        {busy === "canvas" ? "Sign in in the window that opened…" : "Connect Canvas"}
      </button>
      <button disabled={busy !== null} onClick={() => run("prairielearn", connectPrairieLearn)}>
        {busy === "prairielearn" ? "Sign in in the window that opened…" : "Connect PrairieLearn"}
      </button>
      {error && <span className="connect-error">{error}</span>}
    </div>
  );
}

function WorkdayImport({ onImported }) {
  const [term, setTerm] = useState("2026W1");
  const [status, setStatus] = useState(null); // {count} | {error}

  async function handleFile(e) {
    const file = e.target.files[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    try {
      const buf = await file.arrayBuffer();
      const courses = parseWorkdayCourses(buf, term);
      onImported(courses);
      setStatus({ count: courses.length });
    } catch (err) {
      setStatus({ error: err.message });
    }
  }

  return (
    <div className="workday-import">
      <label>
        Term{" "}
        <input
          type="text"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          size={8}
        />
      </label>{" "}
      <label className="file-label">
        Import Workday courses (.xlsx)
        <input type="file" accept=".xlsx" onChange={handleFile} />
      </label>
      {status?.count != null && (
        <span className="import-status">
          Imported {status.count} course{status.count === 1 ? "" : "s"}.
        </span>
      )}
      {status?.error && <span className="connect-error">{status.error}</span>}
    </div>
  );
}

function ItemsTable({ items, sampleMode }) {
  if (items.length === 0) {
    return (
      <p className="empty">
        {sampleMode ? "Nothing upcoming." : "Nothing yet. Connect Canvas or PrairieLearn above."}
      </p>
    );
  }
  const now = new Date();
  return (
    <table>
      <thead>
        <tr>
          <th>Urgency</th>
          <th>Due</th>
          <th>Course</th>
          <th>What</th>
          <th>Kind</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id} className={isOverdue(item, now) ? "overdue" : ""}>
            <td>{displayLabel(item.urgency)}</td>
            <td>{formatDue(item.due)}</td>
            <td>{item.course}</td>
            <td>{item.title}</td>
            <td>{item.kind}</td>
            <td>
              <a href={item.url}>open</a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CoursesTab({ courses, items, sampleMode }) {
  if (courses.length === 0) {
    return (
      <p className="empty">
        {sampleMode ? "No courses." : "Nothing yet. Connect Canvas above."}
      </p>
    );
  }
  return (
    <div className="courses">
      {courses.map((course) => (
        <section key={course.code} className="course-card">
          <h2>
            {course.code} <span className="course-title">{course.title}</span>
          </h2>
          <p className="course-meta">
            {course.term} &middot; Grade: {course.grade == null ? "—" : `${course.grade}%`}
          </p>
          <ItemsTable
            items={sortItems(items.filter((i) => i.course === course.code))}
            sampleMode={sampleMode}
          />
        </section>
      ))}
    </div>
  );
}

export default function Page() {
  const [tab, setTab] = useState("all");
  const [showN, setShowN] = useState(10);
  const [hideOverdue, setHideOverdue] = useState(false);
  // On by default, matching app.py's st.toggle("Sample data", value=True) -
  // NEXT_PUBLIC_HUB_API only decides whether local mode is *possible* (so
  // whether this toggle/the Connect buttons show at all); this state decides
  // what's actually fetched right now, live, without restarting anything.
  const [sampleMode, setSampleMode] = useState(true);
  const [items, setItems] = useState([]);
  const [courses, setCourses] = useState([]);
  const [loadError, setLoadError] = useState(null);

  async function load(useSample) {
    try {
      const [nextItems, nextCourses] = await Promise.all([
        fetchUpcoming(useSample),
        fetchCourses(useSample),
      ]);
      setItems(nextItems);
      setCourses(nextCourses);
      setLoadError(null);
    } catch (e) {
      // Clear stale data on failure - otherwise a failed fetch after
      // switching modes leaves the previous mode's rows on screen under the
      // new mode's caption, which is misleading.
      setItems([]);
      setCourses([]);
      setLoadError(e.message);
    }
  }

  function importWorkdayCourses(imported) {
    // Merge by code: a re-import (or a course already present from
    // Canvas/PrairieLearn/sample data) is updated, not duplicated - but
    // Workday never carries a grade, so don't let it blank out one we
    // already knew (e.g. from Canvas).
    setCourses((prev) => {
      const byCode = new Map(prev.map((c) => [c.code, c]));
      for (const c of imported) {
        const existing = byCode.get(c.code);
        byCode.set(c.code, existing ? { ...existing, ...c, grade: c.grade ?? existing.grade } : c);
      }
      return Array.from(byCode.values());
    });
  }

  useEffect(() => {
    load(sampleMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sampleMode]);

  const now = new Date();
  // Completed items never show, regardless of Hide overdue (matches app.py's
  // df2e178 rule) - filtered once here so it applies to every tab and the
  // Courses tab's per-course lists alike.
  const activeItems = items.filter((item) => !isDone(item));
  const visible = sortItems(activeItems)
    .filter((item) => tab === "all" || tab === "courses" || item.category === tab)
    .filter((item) => !hideOverdue || !isOverdue(item, now))
    .slice(0, showN);

  return (
    <main>
      <h1>UBC Hub</h1>
      <p className="caption">
        Gotham for students: every provider, one pane of glass.{" "}
        {sampleMode ? "(Sample data.)" : "(Local mode: real Canvas/PrairieLearn data.)"}
      </p>

      <WorkdayImport onImported={importWorkdayCourses} />

      {isLocalMode() && (
        <label className="toggle sample-toggle">
          <input
            type="checkbox"
            checked={sampleMode}
            onChange={(e) => setSampleMode(e.target.checked)}
          />{" "}
          Sample data
        </label>
      )}

      {isLocalMode() && !sampleMode && <ConnectBar onConnected={() => load(false)} />}
      {loadError && <p className="connect-error">Couldn&apos;t load: {loadError}</p>}

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab !== "courses" && (
        <div className="controls">
          <label>
            Show next{" "}
            <input
              type="range"
              min={5}
              max={50}
              value={showN}
              onChange={(e) => setShowN(Number(e.target.value))}
            />{" "}
            {showN}
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={hideOverdue}
              onChange={(e) => setHideOverdue(e.target.checked)}
            />{" "}
            Hide overdue
          </label>
        </div>
      )}

      {tab === "courses" ? (
        <CoursesTab courses={courses} items={activeItems} sampleMode={sampleMode} />
      ) : (
        <ItemsTable items={visible} sampleMode={sampleMode} />
      )}
    </main>
  );
}
