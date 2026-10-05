import { test } from "node:test";
import assert from "node:assert/strict";
import {
  fetchUpcoming, fetchCourses, fetchAnnouncements, resetDemoCache,
  migrateLegacyFeedUrl, refreshCanvasFeed, connectCanvasFeed, disconnectCanvasFeed, LEGACY_FEED_KEY,
} from "./hub.js";

const SAMPLE_TITLES = ["Problem Set 3", "Quiz 2", "Midterm 1", "Read ch. 4", "WeBWorK 3"];

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    has: (k) => data.has(k),
  };
}

test("hosted + Sample off, nothing connected: zero rows, no SAMPLE_ROWS, no demo call", async () => {
  resetDemoCache();
  const realFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    return { ok: true, json: async () => ({ items: [{ title: "Problem Set 3" }], announcements: [], courses: [] }) };
  };
  try {
    const items = await fetchUpcoming(false);
    assert.deepEqual(items, []);
    assert.ok(!items.some((i) => SAMPLE_TITLES.includes(i.title)));
    assert.deepEqual(await fetchCourses(false), []);
    assert.deepEqual(await fetchAnnouncements(false), []);
    assert.deepEqual(calls, []); // never even asks /api/demo
  } finally {
    globalThis.fetch = realFetch;
    resetDemoCache();
  }
});

test("hosted + Sample on still falls back to the sample rows", async () => {
  resetDemoCache();
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const items = await fetchUpcoming(true);
    assert.deepEqual(items.map((i) => i.title), SAMPLE_TITLES);
  } finally {
    globalThis.fetch = realFetch;
    resetDemoCache();
  }
});

test("migrateLegacyFeedUrl: POSTs the old key once and deletes it on success", async () => {
  const storage = memoryStorage({ [LEGACY_FEED_KEY]: "https://canvas.ubc.ca/feeds/calendars/x.ics" });
  const calls = [];
  await migrateLegacyFeedUrl(storage, async (url, init) => {
    calls.push({ url, init });
    return { ok: true, status: 200, json: async () => [] };
  });
  assert.equal(storage.has(LEGACY_FEED_KEY), false);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/feed");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.deepEqual(JSON.parse(calls[0].init.body), { url: "https://canvas.ubc.ca/feeds/calendars/x.ics" });
});

test("migrateLegacyFeedUrl: deletes the key even when the POST fails", async () => {
  const storage = memoryStorage({ [LEGACY_FEED_KEY]: "https://canvas.ubc.ca/feeds/calendars/dead.ics" });
  await migrateLegacyFeedUrl(storage, async () => ({ ok: false, status: 400, json: async () => ({ error: "nope" }) }));
  assert.equal(storage.has(LEGACY_FEED_KEY), false);
  const storage2 = memoryStorage({ [LEGACY_FEED_KEY]: "https://canvas.ubc.ca/feeds/calendars/x.ics" });
  await migrateLegacyFeedUrl(storage2, async () => { throw new Error("offline"); });
  assert.equal(storage2.has(LEGACY_FEED_KEY), false);
});

test("migrateLegacyFeedUrl: no key, no request", async () => {
  let called = false;
  await migrateLegacyFeedUrl(memoryStorage(), async () => { called = true; });
  assert.equal(called, false);
});

test("refreshCanvasFeed: GET with credentials, 404 means not connected", async () => {
  let seen;
  const none = await refreshCanvasFeed(async (url, init) => { seen = { url, init }; return { ok: false, status: 404, json: async () => ({ error: "no feed connected" }) }; });
  assert.equal(none, null);
  assert.equal(seen.init.method, "GET");
  assert.equal(seen.init.credentials, "same-origin");
  assert.equal(seen.init.body, undefined);
  const rows = await refreshCanvasFeed(async () => ({ ok: true, status: 200, json: async () => [{ title: "PS4", source: "canvas", url: "u" }] }));
  assert.equal(rows[0].title, "PS4");
});

test("connect POSTs, disconnect DELETEs", async () => {
  const methods = [];
  const fake = async (url, init) => { methods.push(init.method); return { ok: true, status: init.method === "DELETE" ? 204 : 200, json: async () => [] }; };
  await connectCanvasFeed("https://canvas.ubc.ca/feeds/calendars/x.ics", fake);
  await disconnectCanvasFeed(fake);
  assert.deepEqual(methods, ["POST", "DELETE"]);
});
