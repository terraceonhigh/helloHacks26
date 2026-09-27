/* Experimental: Piazza's same-origin JSON RPC. Only pinned/staff posts leave the tab. */
async function capturePiazza(options = {}) {
  const origin = options.origin || location.origin;
  const request = options.fetch || fetch;
  if (origin !== "https://piazza.com") throw new Error("Open piazza.com to sync");
  async function call(method, nid = null, data = {}) {
    const url = new URL("/logic/api", origin);
    url.searchParams.set("method", method);
    url.searchParams.set("aid", `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`);
    const response = await request(url.toString(), {method: "POST", credentials: "same-origin",
      redirect: "error", headers: {"Content-Type": "application/json", Accept: "application/json"},
      body: JSON.stringify({method, params: {nid, ...data}})});
    if (!response.ok) throw new Error(`Piazza RPC failed (${response.status})`);
    const result = await response.json();
    if (result.error) throw new Error(`Piazza rejected ${method}`);
    return result.result;
  }
  const status = await call("user.status");
  const rawNetworks = status?.networks;
  if (!Array.isArray(rawNetworks) || rawNetworks.length > 100) throw new Error("Piazza classes changed shape");
  const networks = [];
  for (const n of rawNetworks) {
    if (typeof n.id !== "string" || !/^[a-zA-Z0-9]+$/.test(n.id)) continue;
    const feed = await call("network.get_my_feed", n.id, {limit: 40, offset: 0, sort: "updated"});
    const posts = [];
    for (const entry of (feed?.feed || []).slice(0, 40)) {
      if (!entry.id || !/^[a-zA-Z0-9]+$/.test(entry.id)) continue;
      const p = await call("content.get", n.id, {cid: entry.id, student_view: null});
      if (!p || !(p.tags || []).some(tag => ["pin", "instructor-note"].includes(tag)) &&
          p.bucket_name !== "Pinned") continue;
      posts.push({id: p.id, tags: (p.tags || []).filter(tag =>
        ["pin", "instructor-note"].includes(tag)), bucket_name: p.bucket_name || "",
        history: [{subject: p.history?.[0]?.subject || p.History?.[0]?.subject || ""}]});
    }
    networks.push({id: n.id, name: n.name || "", course_number: n.course_number || "",
      term: n.term || "", posts});
  }
  const capture = {source: "piazza", origin, networks};
  if (JSON.stringify(capture).length > 1_000_000) throw new Error("Piazza capture exceeds the sync limit");
  return capture;
}

if (typeof module !== "undefined") module.exports = {capturePiazza};
if (typeof chrome !== "undefined" && chrome.runtime?.sendMessage) {
  capturePiazza().then(
    capture => chrome.runtime.sendMessage({type: "CAPTURE_READY", capture}),
    error => chrome.runtime.sendMessage({type: "CAPTURE_FAILED", source: "piazza", error: error.message})
  );
}
