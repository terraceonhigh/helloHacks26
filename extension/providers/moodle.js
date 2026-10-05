/* Experimental: Moodle's own session AJAX JSON. No HTML or password read. */
async function captureMoodle(options = {}) {
  const origin = options.origin || location.origin;
  const request = options.fetch || fetch;
  const key = options.sesskey || globalThis.__hubPageSessionValue;
  delete globalThis.__hubPageSessionValue;
  if (!/^https:\/\//.test(origin) || !/^[a-zA-Z0-9]{6,128}$/.test(key || "")) {
    throw new Error("Moodle session is unavailable");
  }
  const now = Math.floor((options.now || new Date()).getTime() / 1000);
  const calls = [
    {index: 0, methodname: "core_enrol_get_users_courses", args: {userid: 0}},
    {index: 1, methodname: "core_calendar_get_action_events_by_timesort",
     args: {timesortfrom: now - 120 * 86400, timesortto: now + 120 * 86400, limitnum: 100}}
  ];
  const url = new URL("/lib/ajax/service.php", origin);
  url.searchParams.set("sesskey", key);
  url.searchParams.set("info", calls[0].methodname);
  const response = await request(url.toString(), {method: "POST", credentials: "same-origin",
    redirect: "error", headers: {"Content-Type": "application/json", Accept: "application/json"},
    body: JSON.stringify(calls)});
  if (!response.ok) throw new Error(`Moodle AJAX failed (${response.status})`);
  const results = await response.json();
  if (!Array.isArray(results) || results.length !== 2 || results.some(r => r.error)) {
    throw new Error("Moodle did not expose the expected JSON methods");
  }
  const rawCourses = results[0].data;
  const rawEvents = results[1].data?.events;
  if (!Array.isArray(rawCourses) || !Array.isArray(rawEvents) ||
      rawCourses.length > 100 || rawEvents.length > 1000) throw new Error("Moodle JSON shape or size changed");
  const safeUrl = value => {
    if (!value) return "";
    const parsed = new URL(value, origin);
    if (parsed.origin !== origin) throw new Error("Moodle event URL left its origin");
    const id = parsed.searchParams.get("id");
    parsed.search = "";
    if (id && /^\d+$/.test(id)) parsed.searchParams.set("id", id);
    parsed.hash = "";
    return parsed.toString();
  };
  const capture = {source: "moodle", origin,
    courses: rawCourses.map(c => ({shortname: c.shortname || "", fullname: c.fullname || ""})),
    events: rawEvents.map(e => ({id: e.id, name: e.name || "", modulename: e.modulename || "",
      timesort: e.timesort || null, url: safeUrl(e.url),
      course: {shortname: e.course?.shortname || ""}}))};
  if (JSON.stringify(capture).length > 1_000_000) throw new Error("Moodle capture exceeds the sync limit");
  return capture;
}

if (typeof module !== "undefined") module.exports = {captureMoodle};
if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage) {
  captureMoodle().then(
    capture => chrome.runtime.sendMessage({type: "CAPTURE_READY", capture}),
    error => chrome.runtime.sendMessage({type: "CAPTURE_FAILED", source: "moodle", error: error.message})
  );
}
