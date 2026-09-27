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

// Mirrors hub/logic.py's _COURSE_CODE_RE exactly.
const COURSE_CODE_RE = /^(?<faculty>[a-z]{2,5})[ _-]?[a-z]*[ _-]*(?<number>\d{2,4})[ _-]*(?<section>\d{2,4})?/i;

export function normaliseCourseCode(text) {
  const m = COURSE_CODE_RE.exec(text.trim());
  if (!m) return [null, null, null];
  return [m.groups.faculty.toUpperCase(), m.groups.number, m.groups.section ?? null];
}

function findHeaderRow(rows) {
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r] || [];
    for (let c = 0; c < row.length; c++) {
      const value = row[c] == null ? "" : String(row[c]).trim().toLowerCase();
      if (COURSE_HEADER_ALIASES.has(value)) return [r, c];
    }
  }
  return [null, null];
}

function courseFromListing(listing, term) {
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
export function parseWorkdayCourses(arrayBuffer, term) {
  const workbook = XLSX.read(arrayBuffer, { type: "array" });
  const sheetName = workbook.SheetNames.includes(SHEET_NAME) ? SHEET_NAME : workbook.SheetNames[0];
  const sheet = workbook.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: null });

  const [headerRowIndex, courseCol] = findHeaderRow(rows);
  if (headerRowIndex == null) return [];

  const courses = [];
  for (let i = headerRowIndex + 1; i < rows.length; i++) {
    const row = rows[i] || [];
    if (courseCol >= row.length || !row[courseCol]) continue;
    const course = courseFromListing(String(row[courseCol]).trim(), term);
    if (course) courses.push(course);
  }
  return courses;
}
