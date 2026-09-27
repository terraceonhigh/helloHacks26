// Mock data for /mockup (Terrace's paper sketch). FAKE data only.
// Shaped like the shared model in hub/models.py: Item is
// { course, category, kind, title, due, url, source }, due is a
// timezone-aware ISO string. Dues are generated relative to "now" so the
// "N tasks today" headline always has something to count.
import { addDays } from "date-fns";
import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

export const TZ = "America/Vancouver";

// Providers are plugins: the sidebar renders this list, never a hard-coded
// provider. "Yada yada" / "ex" on the sketch read as "more providers".
export const PROVIDERS = [
  { id: "canvas", name: "Canvas" },
  { id: "moodle", name: "Moodle" },
  { id: "prairielearn", name: "PrairieLearn" },
  { id: "gradescope", name: "Gradescope" },
];

export function providerName(source) {
  return PROVIDERS.find((p) => p.id === source)?.name ?? source;
}

// A wall-clock time in Vancouver, `dayOffset` days from today, as an ISO
// string with its UTC offset (timezone-aware, like the backend's `due`).
function vanDue(now, dayOffset, hhmm) {
  const day = formatInTimeZone(addDays(now, dayOffset), TZ, "yyyy-MM-dd");
  const instant = fromZonedTime(`${day}T${hhmm}:00`, TZ);
  return formatInTimeZone(instant, TZ, "yyyy-MM-dd'T'HH:mm:ssXXX");
}

export function mockItems(now) {
  return [
    { course: "FOO 100", category: "task", kind: "assignment", title: "Problem Set 3",
      due: vanDue(now, 0, "23:59"), url: "https://canvas.example/courses/100/assignments/3", source: "canvas" },
    { course: "BARR 200", category: "task", kind: "quiz", title: "Lab 4 pre-lab quiz",
      due: vanDue(now, 0, "17:00"), url: "https://prairielearn.example/course_instance/200/assessment/4", source: "prairielearn" },
    { course: "FIZZ 300", category: "task", kind: "assignment", title: "Essay draft",
      due: vanDue(now, 2, "09:00"), url: "https://canvas.example/courses/300/assignments/7", source: "canvas" },
    { course: "FOO 100", category: "task", kind: "quiz", title: "Week 5 homework",
      due: vanDue(now, 4, "23:59"), url: "https://prairielearn.example/course_instance/100/assessment/5", source: "prairielearn" },
  ];
}

// Placeholder "primed files" per task for the Finder pane. Fetching these is
// an open question on the sketch (LLM agent or heuristic?), so they are static.
export function mockFiles(item) {
  return [
    { name: "Class Notes", type: "folder" },
    { name: "Readings", type: "folder" },
    { name: "template.docx", type: "file" },
  ].map((f) => ({ ...f, id: `${item.url}#${f.name}` }));
}

export function isToday(iso, now) {
  return formatInTimeZone(iso, TZ, "yyyy-MM-dd") === formatInTimeZone(now, TZ, "yyyy-MM-dd");
}

