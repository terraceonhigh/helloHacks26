// Client-side port of hub/workday.py + normalise_course_code, for the hosted
// Vercel site: Workday isn't a login (unlike Canvas/PrairieLearn), just a
// file the student already has, so parsing it entirely in the browser needs
// no backend at all - works identically in Sample and local mode.
//
// This mirrors hub/workday.py's simple, deterministic parsing rules (not
// logic prone to drift like classify_urgency) since Python can't run here.
// Keep the two in sync if either changes.
import * as XLSX from "xlsx";

const SHEET_NAME = "View My Courses";
const COURSE_HEADER_ALIASES = new Set(["course listing", "course"]);

// Mirrors hub/workday.py's _HEADER_ALIASES - both columns ignored until the
// schedule feature (#85), same file/row parseWorkdayCourses already reads.
const HEADER_ALIASES = {
  course: COURSE_HEADER_ALIASES,
  meetingPatterns: new Set(["meeting patterns"]),
  instructionalFormat: new Set(["instructional format"]),
};

// Mirrors hub/logic.py's _COURSE_CODE_RE exactly.
const COURSE_CODE_RE = /^(?<faculty>[a-z]{2,5})[ _-]?[a-z]*[ _-]*(?<number>\d{2,4})[ _-]*(?<section>\d{2,4})?/i;

export function normaliseCourseCode(text) {
  const m = COURSE_CODE_RE.exec(text.trim());
  if (!m) return [null, null, null];
  return [m.groups.faculty.toUpperCase(), m.groups.number, m.groups.section ?? null];
}

// Mirrors hub/workday.py's _find_header_row: the row index plus a
// {logical name: column index} map, built from whichever headers in
// HEADER_ALIASES are present in the row containing "Course Listing"/"Course".
function findHeaderRow(rows) {
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r] || [];
    const found = {};
    for (let c = 0; c < row.length; c++) {
      const value = row[c] == null ? "" : String(row[c]).trim().toLowerCase();
      for (const [name, aliases] of Object.entries(HEADER_ALIASES)) {
        if (aliases.has(value)) found[name] = c;
      }
    }
    if ("course" in found) return [r, found];
  }
  return [null, {}];
}

function cell(row, columns, name) {
  const col = columns[name];
  if (col == null || col >= row.length || row[col] == null) return null;
  return String(row[col]).trim();
}

export function courseFromListing(listing, term) {
  // Mirrors Python's str.partition(" - "): first occurrence only, empty
  // title (falls back to the raw listing) when there's no " - " at all.
  const idx = listing.indexOf(" - ");
  const codePart = idx === -1 ? listing : listing.slice(0, idx);
  const title = idx === -1 ? "" : listing.slice(idx + 3);
  const [faculty, number, section] = normaliseCourseCode(codePart);
  if (!faculty || !number) return null;
  return { code: `${faculty} ${number}`, section, term, title: title.trim() || listing, grade: null };
}

// arrayBuffer: from File.arrayBuffer() (a file the user picked, read
// entirely client-side - never uploaded anywhere).
// Some real Workday exports ship a !ref range that undercounts the actual
// populated cells, so sheet_to_json silently truncates almost everything
// (confirmed against a real export, not just a theoretical worry - matches
// the same fix ubc-workday2cal's prior art needed). Recompute !ref from the
// real cell addresses before reading rows.
// A real Workday "View My Courses" export never has more than a few hundred
// rows/columns - these are generous ceilings, not a tight estimate, just far
// below Excel's actual max (XFD1048576). A stray cell out at that theoretical
// max (seen in a real file) would otherwise blow maxRow/maxCol up to it, and
// sheet_to_json would then try to materialize ~17B cells and hang.
const MAX_SANE_ROW = 10_000;
const MAX_SANE_COL = 500;

export function fixTruncatedRange(sheet) {
  const addresses = Object.keys(sheet).filter((k) => !k.startsWith("!"));
  if (addresses.length === 0) return;
  let maxRow = 0;
  let maxCol = 0;
  for (const addr of addresses) {
    const { r, c } = XLSX.utils.decode_cell(addr);
    if (r > MAX_SANE_ROW || c > MAX_SANE_COL) continue;
    if (r > maxRow) maxRow = r;
    if (c > maxCol) maxCol = c;
  }
  sheet["!ref"] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: maxRow, c: maxCol } });
}

export function parseWorkdayCourses(arrayBuffer, term) {
  const workbook = XLSX.read(arrayBuffer, { type: "array" });
  const sheetName = workbook.SheetNames.includes(SHEET_NAME) ? SHEET_NAME : workbook.SheetNames[0];
  const sheet = workbook.Sheets[sheetName];
  fixTruncatedRange(sheet);
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: null });

  const [headerRowIndex, columns] = findHeaderRow(rows);
  if (headerRowIndex == null) return [];

  // Real exports have one row per meeting component (Lecture, Lab,
  // Tutorial...), each repeating the same course listing text - confirmed
  // against a real export, not a theoretical worry. Dedupe by code, keeping
  // the first occurrence.
  const courses = [];
  const seenCodes = new Set();
  for (let i = headerRowIndex + 1; i < rows.length; i++) {
    const row = rows[i] || [];
    const listing = cell(row, columns, "course");
    if (!listing) continue;
    const course = courseFromListing(listing, term);
    if (course && !seenCodes.has(course.code)) {
      seenCodes.add(course.code);
      courses.push(course);
    }
  }
  return courses;
}

const DAY_CODES = { mon: "MO", tue: "TU", wed: "WE", thu: "TH", fri: "FR", sat: "SA", sun: "SU" };

// Mirrors hub/workday.py's _KIND_FOR_FORMAT.
const KIND_FOR_FORMAT = {
  lecture: "lecture", laboratory: "lab", seminar: "seminar",
  tutorial: "tutorial", discussion: "tutorial", exam: "exam", "final exam": "exam",
};

const TIME_RE = /^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$/i;

// "10:00 a.m." -> "10:00" (24h) or null if unrecognized. Mirrors
// hub/workday.py's _parse_time; returns a string, not a Date, since a
// Meeting's start/end time is a naive recurring wall-clock time, not a
// single instant (see hub.models.Meeting).
function parseTime(text) {
  const m = TIME_RE.exec(text.trim());
  if (!m) return null;
  let hour = Number(m[1]) % 12;
  if (m[3].toLowerCase() === "p") hour += 12;
  return `${String(hour).padStart(2, "0")}:${m[2]}`;
}

// Mirrors hub/workday.py's _parse_meeting_pattern: one "Meeting Patterns"
// cell holds one line per meeting component, each shaped like
// "2026-09-08 - 2026-12-05 | Mon Wed Fri | 10:00 a.m. - 11:00 a.m. | Building | Room 100".
// A line can also be a bare "-" or otherwise unparseable (an async/online
// component, a TBD exam slot) - skipped rather than guessed at.
function parseMeetingPattern(pattern, courseCode, kind, source) {
  const meetings = [];
  for (const line of pattern.split("\n")) {
    const parts = line.split("|").map((p) => p.trim());
    if (parts.length < 3) continue;
    const [dateRange, daysText, timesText, ...locationParts] = parts;
    const [startStr, endStr] = dateRange.split(" - ").map((d) => d.trim());
    if (!startStr || !endStr || !/^\d{4}-\d{2}-\d{2}$/.test(startStr) || !/^\d{4}-\d{2}-\d{2}$/.test(endStr)) continue;
    const days = daysText.split(/\s+/).map((d) => DAY_CODES[d.slice(0, 3).toLowerCase()]).filter(Boolean);
    if (days.length === 0) continue;
    const [startText, endText] = timesText.split(" - ").map((t) => (t ?? "").trim());
    const startTime = startText ? parseTime(startText) : null;
    const endTime = endText ? parseTime(endText) : null;
    if (!startTime || !endTime) continue;
    meetings.push({
      course: courseCode, kind, days, startTime, endTime,
      location: locationParts.filter(Boolean).join(", "),
      termStart: startStr, termEnd: endStr, source,
    });
  }
  return meetings;
}

// Client-side mirror of hub/workday.py's parse_workday_schedule - same
// "Meeting Patterns"/"Instructional Format" columns, same file
// parseWorkdayCourses already reads. Returns [] (never throws) on an older
// export missing those columns.
export function parseWorkdaySchedule(arrayBuffer, term, source = "workday") {
  const workbook = XLSX.read(arrayBuffer, { type: "array" });
  const sheetName = workbook.SheetNames.includes(SHEET_NAME) ? SHEET_NAME : workbook.SheetNames[0];
  const sheet = workbook.Sheets[sheetName];
  fixTruncatedRange(sheet);
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: null });

  const [headerRowIndex, columns] = findHeaderRow(rows);
  if (headerRowIndex == null || columns.meetingPatterns == null) return [];

  const meetings = [];
  for (let i = headerRowIndex + 1; i < rows.length; i++) {
    const row = rows[i] || [];
    const listing = cell(row, columns, "course");
    const pattern = cell(row, columns, "meetingPatterns");
    if (!listing || !pattern) continue;
    const course = courseFromListing(listing, term);
    if (!course) continue;
    const formatText = (cell(row, columns, "instructionalFormat") || "").toLowerCase();
    const kind = KIND_FOR_FORMAT[formatText] ?? "class";
    meetings.push(...parseMeetingPattern(pattern, course.code, kind, source));
  }
  return meetings;
}

// Turn imported class meetings into one .ics the student can add to Apple,
// Google or Outlook Calendar - the same output as
// github.com/terraceonhigh/ubc-workday-ics: one weekly recurring event per
// meeting in America/Vancouver time, optional reminders `reminders` minutes
// before each class. Pure (no DOM) so it's testable; the page wraps it in a
// Blob download.
const VANCOUVER_TZ = [
  "BEGIN:VTIMEZONE", "TZID:America/Vancouver",
  "BEGIN:DAYLIGHT", "TZOFFSETFROM:-0800", "TZOFFSETTO:-0700", "TZNAME:PDT", "DTSTART:19700308T020000", "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU", "END:DAYLIGHT",
  "BEGIN:STANDARD", "TZOFFSETFROM:-0700", "TZOFFSETTO:-0800", "TZNAME:PST", "DTSTART:19701101T020000", "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "END:STANDARD",
  "END:VTIMEZONE",
];
const ICAL_WEEKDAY = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

const icsText = (s) => String(s ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
const compactDate = (iso) => iso.replaceAll("-", "");
const compactTime = (hhmm) => `${hhmm.replace(":", "")}00`;

// RFC 5545 caps lines at 75 octets; longer ones continue on a line starting with a space.
function fold(line) {
  const out = [];
  while (line.length > 75) { out.push(line.slice(0, 75)); line = " " + line.slice(75); }
  out.push(line);
  return out;
}

// The first date on/after termStart that falls on one of the meeting's days.
function firstOccurrence(termStart, days) {
  const d = new Date(`${termStart}T00:00:00Z`);
  for (let i = 0; i < 7; i++, d.setUTCDate(d.getUTCDate() + 1)) {
    if (days.includes(ICAL_WEEKDAY[d.getUTCDay()])) return d.toISOString().slice(0, 10);
  }
  return termStart;
}

export function meetingsToIcs(meetings, { reminders = [], now = new Date() } = {}) {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Lauds//Class schedule//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Lauds classes", ...VANCOUVER_TZ];
  for (const m of meetings) {
    const day = compactDate(firstOccurrence(m.termStart, m.days));
    // UNTIL must be UTC when DTSTART has a TZID. 07:59:59Z the next day is
    // 23:59:59 Vancouver time in PST, and 00:59:59 in PDT - no class meets then.
    const end = new Date(`${m.termEnd}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 1);
    const until = `${compactDate(end.toISOString().slice(0, 10))}T075959Z`;
    const uid = `${[m.course, m.kind, m.days.join(""), m.startTime, m.termStart].join("-").replace(/[^A-Za-z0-9-]/g, "")}@lauds`;
    lines.push(
      "BEGIN:VEVENT", `UID:${uid}`, `DTSTAMP:${stamp}`,
      `DTSTART;TZID=America/Vancouver:${day}T${compactTime(m.startTime)}`,
      `DTEND;TZID=America/Vancouver:${day}T${compactTime(m.endTime)}`,
      `RRULE:FREQ=WEEKLY;BYDAY=${m.days.join(",")};UNTIL=${until}`,
      `SUMMARY:${icsText(`${m.course} ${m.kind}`)}`,
    );
    if (m.location) lines.push(`LOCATION:${icsText(m.location)}`);
    for (const min of reminders) {
      lines.push("BEGIN:VALARM", "ACTION:DISPLAY", `TRIGGER:-PT${min}M`, `DESCRIPTION:${icsText(`${m.course} in ${min} minutes`)}`, "END:VALARM");
    }
    lines.push("END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.flatMap(fold).join("\r\n") + "\r\n";
}

// "10, 30" -> [10, 30]; anything that isn't a whole number of minutes up to a
// week is dropped rather than guessed at.
export function parseReminders(text) {
  return [...new Set(String(text ?? "").split(/[,\s]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0 && n <= 10080))];
}
