/* Experimental: Blackboard REST JSON course membership; no due-date API verified. */
async function captureBlackboard(options = {}) {
  const origin = options.origin || location.origin;
  const request = options.fetch || fetch;
  if (!/^https:\/\//.test(origin)) throw new Error("Blackboard requires HTTPS");
  async function get(path) {
    const url = new URL(path, origin);
    if (url.origin !== origin || !url.pathname.startsWith("/learn/api/public/v1/")) {
      throw new Error("Blackboard pagination left its API origin");
    }
    const response = await request(url.toString(), {credentials: "same-origin", redirect: "error",
      headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`Blackboard REST failed (${response.status})`);
    return response.json();
  }
  const me = await get("/learn/api/public/v1/users/me");
  if (!me?.id || !/^[\w-]+$/.test(me.id)) throw new Error("Blackboard user ID unavailable");
  const memberships = [];
  let path = `/learn/api/public/v1/users/${encodeURIComponent(me.id)}/courses`;
  for (let page = 0; path && page < 10; page++) {
    const result = await get(path);
    if (!Array.isArray(result.results)) throw new Error("Blackboard memberships changed shape");
    memberships.push(...result.results);
    if (memberships.length > 100) throw new Error("Blackboard course limit exceeded");
    path = result.paging?.nextPage || null;
  }
  if (path) throw new Error("Blackboard pagination limit exceeded");
  const courses = [];
  for (const membership of memberships) {
    const id = membership.courseId;
    if (!id || !/^[\w-]+$/.test(id)) continue;
    const c = await get(`/learn/api/public/v1/courses/${encodeURIComponent(id)}?expand=term`);
    courses.push({id: c.id, courseId: c.courseId || "", name: c.name || "",
      term: {name: c.term?.name || ""}});
  }
  const capture = {source: "blackboard", origin, courses};
  if (JSON.stringify(capture).length > 1_000_000) throw new Error("Blackboard capture exceeds the sync limit");
  return capture;
}

if (typeof module !== "undefined") module.exports = {captureBlackboard};
if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage) {
  captureBlackboard().then(
    capture => chrome.runtime.sendMessage({type: "CAPTURE_READY", capture}),
    error => chrome.runtime.sendMessage({type: "CAPTURE_FAILED", source: "blackboard", error: error.message})
  );
}
