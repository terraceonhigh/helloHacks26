/* Capture only Canvas JSON needed by hub.canvas's shared-model mapper.
   This file runs in the signed-in Canvas tab; it never reads or sends cookies. */
async function captureCanvas(options = {}) {
  const origin = options.origin || location.origin;
  const request = options.fetch || fetch;
  if (origin !== "https://canvas.ubc.ca") {
    throw new Error("Open canvas.ubc.ca to sync");
  }

  async function getAll(path, params) {
    let url = new URL(path, origin);
    for (const [key, value] of Object.entries(params)) {
      for (const entry of Array.isArray(value) ? value : [value]) url.searchParams.append(key, entry);
    }
    const rows = [];
    for (let page = 0; url && page < 30; page++) {
      if (url.origin !== origin || !url.pathname.startsWith("/api/v1/")) {
        throw new Error("Canvas pagination left the allowed origin");
      }
      const response = await request(url.toString(), {
        credentials: "same-origin", redirect: "error",
        headers: {Accept: "application/json"}
      });
      if (!response.ok) throw new Error(`Canvas request failed (${response.status})`);
      const text = (await response.text()).replace(/^while\(1\);/, "");
      const batch = JSON.parse(text);
      if (!Array.isArray(batch)) throw new Error("Canvas returned an unexpected response");
      rows.push(...batch);
      if (rows.length > 3000) throw new Error("Canvas response exceeds the sync limit");
      const link = response.headers.get("link") || "";
      const next = link.match(/<([^>]+)>;\s*rel="?next"?/i);
      url = next ? new URL(next[1], origin) : null;
    }
    if (url) throw new Error("Canvas pagination exceeds the sync limit");
    return rows;
  }

  function safeUrl(value) {
    if (!value) return "";
    const url = new URL(value, origin);
    if (url.origin !== origin) return "";
    // Assignment links need only the path. Calendar events need their ID.
    const eventId = url.searchParams.get("event_id");
    const context = url.searchParams.get("include_contexts");
    url.search = "";
    if (eventId && /^\d+$/.test(eventId)) url.searchParams.set("event_id", eventId);
    if (context && /^course_\d+$/.test(context)) url.searchParams.set("include_contexts", context);
    url.hash = "";
    return url.toString();
  }

  const now = options.now || new Date();
  const start = new Date(now.getTime() - 120 * 86400000).toISOString().slice(0, 10);
  const end = new Date(now.getTime() + 120 * 86400000).toISOString().slice(0, 10);
  const rawCourses = await getAll("/api/v1/courses", {
    "include[]": ["total_scores", "term"], enrollment_state: "active", per_page: "100"
  });
  if (rawCourses.length > 100) throw new Error("Too many Canvas courses to sync");
  const courses = rawCourses.map(c => ({
    id: c.id, course_code: c.course_code || "", name: c.name || "",
    term: {name: c.term?.name || ""},
    enrollments: (c.enrollments || []).slice(0, 1).map(e => ({
      computed_current_score: e.computed_current_score ?? null
    }))
  }));
  const rawPlanner = await getAll("/api/v1/planner/items", {
    start_date: start, end_date: end, per_page: "100"
  });
  const planner = rawPlanner.map(p => ({
    course_id: p.course_id, context_name: p.context_name || "",
    plannable_type: p.plannable_type || "", plannable_date: p.plannable_date || null,
    plannable: {title: p.plannable?.title || ""}, html_url: safeUrl(p.html_url),
    submissions: typeof p.submissions === "object" && p.submissions !== null ? {
      submitted: Boolean(p.submissions.submitted), excused: Boolean(p.submissions.excused)
    } : false,
    planner_override: {marked_complete: Boolean(p.planner_override?.marked_complete)}
  }));
  const undated = [];
  for (const c of rawCourses) {
    const assignments = await getAll(`/api/v1/courses/${encodeURIComponent(c.id)}/assignments`, {per_page: "100"});
    for (const a of assignments) {
      if (a.due_at) continue;
      undated.push({
        course_id: c.id, name: a.name || "", due_at: null,
        html_url: safeUrl(a.html_url),
        has_submitted_submissions: Boolean(a.has_submitted_submissions)
      });
    }
  }
  const capture = {source: "canvas", captured_at: now.toISOString(), courses, planner, undated};
  if (JSON.stringify(capture).length > 1_000_000) {
    throw new Error("Canvas data exceeds the sync size limit");
  }
  return capture;
}

if (typeof module !== "undefined") module.exports = {captureCanvas};
if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage) {
  captureCanvas().then(
    capture => chrome.runtime.sendMessage({type: "CAPTURE_READY", capture}),
    error => chrome.runtime.sendMessage({type: "CAPTURE_FAILED", source: "canvas", error: error.message})
  );
}
