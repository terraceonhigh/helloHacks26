"use client";

import { useEffect, useState } from "react";
import {
  connectCanvas,
  connectPrairieLearn,
  fetchCourses,
  fetchUpcoming,
  isDone,
  isLocalMode,
  isOverdue,
  sortItems,
} from "../lib/hub";

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

function ItemsTable({ items }) {
  if (items.length === 0) {
    return (
      <p className="empty">
        {isLocalMode() ? "Nothing yet. Connect Canvas or PrairieLearn above." : "Nothing upcoming."}
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
            <td>{item.urgency ?? "—"}</td>
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

function CoursesTab({ courses, items }) {
  if (courses.length === 0) {
    return (
      <p className="empty">
        {isLocalMode() ? "Nothing yet. Connect Canvas above." : "No courses."}
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
          <ItemsTable items={sortItems(items.filter((i) => i.course === course.code))} />
        </section>
      ))}
    </div>
  );
}

export default function Page() {
  const [tab, setTab] = useState("all");
  const [showN, setShowN] = useState(10);
  const [hideOverdue, setHideOverdue] = useState(false);
  const [items, setItems] = useState([]);
  const [courses, setCourses] = useState([]);
  const [loadError, setLoadError] = useState(null);

  async function load() {
    try {
      const [nextItems, nextCourses] = await Promise.all([fetchUpcoming(), fetchCourses()]);
      setItems(nextItems);
      setCourses(nextCourses);
      setLoadError(null);
    } catch (e) {
      setLoadError(e.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

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

      {isLocalMode() && <ConnectBar onConnected={load} />}
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
        <CoursesTab courses={courses} items={activeItems} />
      ) : (
        <ItemsTable items={visible} />
      )}
    </main>
  );
}
