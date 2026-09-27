"use client";

// /mockup: a working build of Terrace's paper dashboard sketch.
// Left: connections. Centre: "N tasks today" + one row per task.
// Right: a Finder-style view of the selected row's files (placeholders).

import { useEffect, useMemo, useState } from "react";
import {
  columnOrderingFeature,
  createColumnHelper,
  functionalUpdate,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { formatInTimeZone } from "date-fns-tz";
import {
  ArrowLeftRight,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  PanelLeft,
  PanelRight,
} from "lucide-react";
import { PROVIDERS, TZ, isToday, mockFiles, mockItems, providerName } from "./data";
import styles from "./mockup.module.css";

const features = tableFeatures({ columnOrderingFeature });
const helper = createColumnHelper();
const EMPTY = [];
const WIDE = "(min-width: 900px)";
const COURSE_FIRST = ["course", "due", "files", "submit"];
const DATE_FIRST = ["due", "course", "files", "submit"];

// null = follow the screen width (open on wide, closed on phone), so the
// server render and first paint agree; a click pins it open or closed.
function usePanel() {
  const [open, setOpen] = useState(null);
  const toggle = () =>
    setOpen((o) => !(o ?? window.matchMedia(WIDE).matches));
  const attr = open === null ? "auto" : open ? "open" : "closed";
  return [attr, toggle, open ?? null];
}

export default function Mockup() {
  const [now, setNow] = useState(null);
  useEffect(() => setNow(new Date()), []); // dues are relative to the viewer's today

  const items = useMemo(() => (now ? mockItems(now) : EMPTY), [now]);
  const todayCount = now ? items.filter((i) => isToday(i.due, now)).length : 0;

  const [left, toggleLeft] = usePanel();
  const [right, toggleRight, rightPinned] = usePanel();
  const [selectedUrl, setSelectedUrl] = useState(null);
  const [columnOrder, setColumnOrder] = useState(COURSE_FIRST);
  const dateFirst = columnOrder[0] === "due";
  const selected = items.find((i) => i.url === selectedUrl) ?? null;

  function openFiles(item) {
    setSelectedUrl(item.url);
    const isOpen = rightPinned ?? window.matchMedia(WIDE).matches;
    if (!isOpen) toggleRight();
  }

  const columns = useMemo(
    () =>
      helper.columns([
        helper.accessor("course", {
          id: "course",
          header: "Course",
          cell: ({ row }) => (
            <div className={styles.courseCell}>
              <span className={styles.courseCode}>{row.original.course}</span>
              <span className={styles.taskTitle}>{row.original.title}</span>
            </div>
          ),
        }),
        helper.accessor("due", {
          id: "due",
          header: "Due",
          cell: ({ getValue }) => {
            const iso = getValue();
            return (
              <time
                className={styles.mmdd}
                dateTime={iso}
                title={formatInTimeZone(iso, TZ, "EEE d MMM, h:mm a zzz")}
              >
                {formatInTimeZone(iso, TZ, "MMdd")}
              </time>
            );
          },
        }),
        helper.display({
          id: "files",
          header: "Readings & other",
          cell: ({ row }) => {
            const item = row.original;
            const active = item.url === selectedUrl;
            return (
              <button
                type="button"
                className={styles.linkButton}
                aria-pressed={active}
                onClick={() => openFiles(item)}
              >
                {active ? <FolderOpen size={16} aria-hidden /> : <Folder size={16} aria-hidden />}
                Homework, readings &amp; other
              </button>
            );
          },
        }),
        helper.display({
          id: "submit",
          header: "Submit",
          cell: ({ row }) => (
            <a
              className={styles.submitLink}
              href={row.original.url}
              target="_blank"
              rel="noreferrer"
            >
              Submit on {providerName(row.original.source)}
              <ExternalLink size={14} aria-hidden />
            </a>
          ),
        }),
      ]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedUrl, rightPinned],
  );

  const table = useTable({
    features,
    columns,
    data: items,
    getRowId: (item) => item.url, // identity is (source, url); url is unique here
    state: { columnOrder },
    onColumnOrderChange: (u) => setColumnOrder((prev) => functionalUpdate(u, prev)),
  });

  return (
    <div className={styles.shell} data-left={left} data-right={right}>
      <aside id="mockup-left" className={styles.left} aria-label="Connections">
        <h2 className={styles.paneHeading}>Connections:</h2>
        <ul className={styles.providers}>
          {PROVIDERS.map((p) => (
            <li key={p.id} className={styles.providerCard}>{p.name}</li>
          ))}
        </ul>
      </aside>

      <main className={styles.centre}>
        <div className={styles.topbar}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={toggleLeft}
            aria-label="Toggle connections sidebar"
            aria-controls="mockup-left"
          >
            <PanelLeft size={20} aria-hidden />
          </button>
          <h1 className={styles.headline}>
            {now ? `${todayCount} ${todayCount === 1 ? "task" : "tasks"} today` : " "}
          </h1>
          <button
            type="button"
            className={styles.iconButton}
            onClick={toggleRight}
            aria-label="Toggle files sidebar"
            aria-controls="mockup-right"
          >
            <PanelRight size={20} aria-hidden />
          </button>
        </div>

        <div className={styles.swapRow}>
          <button
            type="button"
            className={styles.swapButton}
            aria-pressed={dateFirst}
            onClick={() => table.setColumnOrder(dateFirst ? COURSE_FIRST : DATE_FIRST)}
          >
            <ArrowLeftRight size={16} aria-hidden />
            Swap? {dateFirst ? "date first" : "course first"}
          </button>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.table} data-order={dateFirst ? "date-first" : "course-first"}>
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => (
                    <th key={header.id} scope="col">
                      <table.FlexRender header={header} />
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={row.original.url === selectedUrl ? styles.selectedRow : undefined}
                >
                  {row.getAllCells().map((cell) => (
                    <td key={cell.id}>
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      <aside id="mockup-right" className={styles.right} aria-label="Files">
        <h2 className={styles.paneHeading}>
          {selected ? `${selected.course}: ${selected.title}` : "Files"}
        </h2>
        {selected ? (
          <ul className={styles.finder}>
            {mockFiles(selected).map((f) => (
              <li key={f.id} className={styles.finderItem}>
                {f.type === "folder" ? (
                  <Folder className={styles.finderIcon} size={48} strokeWidth={1.25} aria-hidden />
                ) : (
                  <FileText className={styles.finderIcon} size={48} strokeWidth={1.25} aria-hidden />
                )}
                <span className={styles.finderName}>{f.name}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.hint}>Choose a task&rsquo;s readings link to see its files.</p>
        )}
        <p className={styles.placeholder}>Placeholder files. Fetching them isn&rsquo;t built yet.</p>
      </aside>
    </div>
  );
}
