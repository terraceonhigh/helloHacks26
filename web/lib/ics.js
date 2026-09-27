// Minimal .ics parser for the hosted Vercel site's /api/feed route (#47).
// A JS port of hub/ics.py's parse(), not an import of it: /api/feed runs on
// Vercel's JS runtime, and hub/ is a Python package. Keep this a literal
// mirror of hub/ics.py - a fix there (rule 1's "one model" logic) needs the
// same fix here too.

const COURSE_SUFFIX = /\s*\[(.+?)\]\s*$/;

// Canvas's own UID shape for planner-backed events, e.g. "event-assignment-99"
// or "event-calendar-event-55". Feeds that don't use it (Moodle, so far) fall
// back to the URL-sniffing heuristic below.
const UID_RE = /^event-(assignment|calendar-event)-(\d+)$/;
const COURSE_ID_RE = /include_contexts=course_(\d+)/;

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

function categoryFor(kind) {
  return CATEGORY_FOR[kind] ?? "task";
}

function parseVevent(block) {
  // RFC 5545 line folding: a continuation line starts with a space/tab.
  const unfolded = block.replace(/\r\n/g, "\n").replace(/\n[ \t]/g, "");
  const fields = {};
  for (const line of unfolded.split("\n")) {
    const m = line.match(/^([A-Z-]+)(?:;[^:]*)?:(.*)$/);
    if (m) fields[m[1]] = m[2];
  }
  return fields;
}

function parseDtstart(value) {
  // Feeds we've seen (Canvas, self-hosted) are always UTC ("...Z"); a bare
  // date with no time is an all-day event.
  const m = value.match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})Z?)?$/);
  if (!m) return null;
  const [, y, mo, d, h = "00", mi = "00", s = "00"] = m;
  return new Date(Date.UTC(+y, +mo - 1, +d, +h, +mi, +s)).toISOString();
}

// ics text -> list of Item-shaped rows. `origin` (scheme://host) rebuilds a
// deep link from Canvas's UID; pass the feed URL's own origin, since events
// live on the same host.
export function parseIcs(icsText, source, origin = "") {
  const blocks = icsText.replace(/\r\n/g, "\n").split("BEGIN:VEVENT").slice(1);
  return blocks.map((raw) => {
    const f = parseVevent(raw.split("END:VEVENT")[0]);
    const summary = f.SUMMARY || "";
    const courseMatch = summary.match(COURSE_SUFFIX);
    const rawUrl = f.URL || "";
    const uidMatch = (f.UID || "").match(UID_RE);

    let kind, url;
    if (uidMatch) {
      // Canvas's ics `URL` is the generic course-calendar page for every
      // event, assignment or not - the same link for every item in a
      // course, which breaks both `kind` (decided by the link) and identity,
      // which is (source, url) (#15/#47). UID is per-item; use it instead.
      const [, kindKey, itemId] = uidMatch;
      kind = kindKey === "assignment" ? "assignment" : "event";
      const courseIdMatch = rawUrl.match(COURSE_ID_RE);
      url = kind === "assignment" && courseIdMatch
        ? `${origin}/courses/${courseIdMatch[1]}/assignments/${itemId}`
        : `${origin}/calendar?event_id=${itemId}`;
    } else {
      kind = rawUrl.includes("/calendar_events/") ? "event" : "assignment";
      url = rawUrl;
    }

    return {
      course: courseMatch ? courseMatch[1] : "",
      category: categoryFor(kind),
      kind,
      title: summary.replace(COURSE_SUFFIX, ""),
      due: f.DTSTART ? parseDtstart(f.DTSTART) : null,
      url,
      source,
      done: null,
    };
  });
}
