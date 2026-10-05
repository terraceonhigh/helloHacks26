import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

test("uploads a Canvas capture to Vercel without browser session credentials", async () => {
  const handlers = {};
  const stored = {syncKey: "fake-hub-key"};
  const calls = [];
  const chrome = {
    storage: {local: {
      setAccessLevel: async () => {},
      get: async () => stored,
      set: async value => Object.assign(stored, value)
    }},
    runtime: {onInstalled: {addListener: fn => { handlers.installed = fn; }},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: () => {}}},
    alarms: {create: () => {}, onAlarm: {addListener: fn => { handlers.alarm = fn; }}},
    tabs: {query: async () => [], create: async () => {}},
    scripting: {executeScript: async () => {}}
  };
  const normalized = {source: "canvas", stored: false, courses: [], items: []};
  const fetch = async (url, init) => {
    calls.push({url, init});
    return {ok: true, status: 200, json: async () => normalized};
  };
  const registry = fs.readFileSync(new URL("./providers.js", import.meta.url), "utf8");
  const context = {chrome, fetch, Date, JSON, URL, setTimeout,
    importScripts: () => vm.runInNewContext(registry, context)};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"),
                     context);
  const capture = {source: "canvas", courses: [], planner: [], undated: []};
  handlers.message({type: "CAPTURE_READY", capture},
                   {tab: {url: "https://canvas.ubc.ca/courses"}}, () => {});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "https://hello-hacks26.vercel.app/api/normalize");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), capture);
  assert.equal(calls[1].url, "https://hello-hacks26.vercel.app/api/sync");
  assert.equal(calls[1].init.headers.Authorization, "Bearer fake-hub-key");
  assert.deepEqual(JSON.parse(calls[1].init.body), normalized);
  assert.match(stored.syncStatus, /^Canvas uploaded at /);
  assert.deepEqual(stored.latestCaptures.canvas, capture);
  assert.deepEqual(stored.latestModels.canvas, normalized);

  handlers.message({type: "CAPTURE_READY", capture},
                   {tab: {url: "https://evil.example/"}}, () => {});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(calls.length, 2);
});

test("keeps a capture local when the hosted sync key is not configured", async () => {
  const handlers = {};
  const stored = {};
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => stored,
                      set: async value => Object.assign(stored, value)}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: () => {}}},
    alarms: {create: () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async () => [], create: async () => {}},
    scripting: {executeScript: async () => {}}
  };
  const registry = fs.readFileSync(new URL("./providers.js", import.meta.url), "utf8");
  const context = {chrome, fetch: () => { throw new Error("unexpected network call"); }, Date, JSON, URL,
    importScripts: () => vm.runInNewContext(registry, context)};
  context.fetch = async () => ({ok: true, status: 200, json: async () =>
    ({source: "canvas", stored: false, courses: [], items: []})});
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  const capture = {source: "canvas", courses: [], planner: [], undated: []};
  handlers.message({type: "CAPTURE_READY", capture},
                   {tab: {url: "https://canvas.ubc.ca/"}}, () => {});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(stored.latestCaptures.canvas, capture);
  assert.deepEqual(stored.latestModels.canvas.items, []);
  assert.match(stored.syncStatus, /saved locally/);
});

test("the transport runs another registered provider without provider-specific code", async () => {
  const handlers = {};
  const injections = [];
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => ({}),
                      set: async () => {}}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: () => {}}},
    alarms: {create: () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async query => {
      assert.equal(query.url, "https://moodle.example/*");
      return [{id: 9, status: "complete"}];
    }, create: async () => {}},
    scripting: {executeScript: async args => injections.push(args)}
  };
  const context = {chrome, URL, importScripts: () => {},
    HUB_PROVIDERS: [{id: "moodle", label: "Moodle", origin: "https://moodle.example",
                     tabPattern: "https://moodle.example/*", captureFile: "providers/moodle.js"}]};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  const result = await new Promise(resolve =>
    handlers.message({type: "SYNC_NOW", provider: "moodle"}, {}, resolve));
  assert.equal(result.ok, true);
  assert.equal(injections[0].target.tabId, 9);
  assert.equal(injections[0].files[0], "providers/moodle.js");
});

test("a configured school origin controls custom-provider injection and sender validation", async () => {
  const handlers = {};
  const injections = [];
  const stored = {providerOrigins: {blackboard: "https://bb.example.edu"}};
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => stored,
                      set: async value => Object.assign(stored, value)}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: () => {}}},
    alarms: {create: () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async query => {
      assert.equal(query.url, "https://bb.example.edu/*");
      return [{id: 4, status: "complete"}];
    }, create: async () => {}},
    scripting: {executeScript: async args => injections.push(args)}
  };
  const context = {chrome, URL, fetch: async () => { throw Error("unexpected upload"); },
    HUB_PROVIDERS: [{id: "blackboard", label: "Blackboard", customOrigin: true,
      captureFile: "providers/blackboard.js"}], importScripts: () => {}};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  const result = await new Promise(resolve =>
    handlers.message({type: "SYNC_NOW", provider: "blackboard"}, {}, resolve));
  assert.equal(result.ok, true);
  assert.equal(injections[0].files[0], "providers/blackboard.js");
  handlers.message({type: "CAPTURE_FAILED", source: "blackboard", error: "fake"},
    {tab: {url: "https://other.example/"}}, () => {});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.notEqual(stored.syncStatus, "fake");
});

test("navigated provider opens every course page and captures all rows", async () => {
  const handlers = {};
  const stored = {syncKey: "fake-key", latestCaptures: {prairielearn: {source: "prairielearn"}}};
  const visited = [];
  let onUpdated;
  const origin = "https://us.prairielearn.com";
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => stored,
                      set: async value => Object.assign(stored, value)}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: fn => { handlers.external = fn; }}},
    alarms: {create: () => {}, onAlarm: {addListener: fn => { handlers.alarm = fn; }}},
    tabs: {query: async () => [{id: 7, status: "complete"}], create: async () => {},
      onUpdated: {addListener: fn => { onUpdated = fn; }, removeListener: () => {}},
      update: async (id, {url}) => {
        visited.push(url);
        setTimeout(() => onUpdated(id, {status: "complete"}, {id, url}), 0);
      }},
    scripting: {executeScript: async ({files}) => [{result:
      files[0].endsWith("index.js") ? [
        {ci_id: "1", title: "CPSC 101: Intro, 2026 Winter Term 1"},
        {ci_id: "2", title: "CPSC 102: Intro, 2026 Winter Term 1"}
      ] : {ci_id: visited.at(-1).match(/\/(\d+)\/assessments$/)[1], assessments: [
        {title: "Quiz", group: "Quizzes", href: "", due_text: "", score_text: "",
         credit_empty: false}
      ]}
    }]}
  };
  const context = {chrome, URL, Date, JSON, setTimeout, clearTimeout,
    fetch: async () => ({ok: true, json: async () =>
      ({source: "prairielearn", stored: false, courses: [], items: []})}),
    HUB_PROVIDERS: [{id: "prairielearn", label: "PrairieLearn", origin,
      indexFile: "providers/prairielearn-index.js", pageFile: "providers/prairielearn-assessments.js",
      courseIdField: "ci_id", courseIdPattern: /^\d+$/,
      pagePathTemplate: "/pl/course_instance/{id}/assessments", rowsKey: "assessments"}],
    importScripts: () => {}};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  handlers.alarm({name: "provider-sync"});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(visited, []);
  const result = await new Promise(resolve =>
    handlers.message({type: "SYNC_NOW", provider: "prairielearn"}, {}, resolve));
  assert.equal(result.ok, true);
  assert.deepEqual(visited, [origin + "/", origin + "/pl/course_instance/1/assessments",
    origin + "/pl/course_instance/2/assessments"]);
  assert.equal(stored.latestCaptures.prairielearn.courses.length, 2);
  assert.equal(stored.latestCaptures.prairielearn.courses[1].assessments.length, 1);
  const everywhere = await new Promise(resolve => handlers.external({type: "SYNC_ALL"},
    {url: "https://hello-hacks26.vercel.app/"}, resolve));
  assert.equal(everywhere.results[0].ok, true);
  assert.equal(visited.length, 6); // SYNC_ALL takes the same interactive navigation path.
});

test("SYNC_ALL skips never-connected providers and waits for DOM capture upload", async () => {
  const handlers = {};
  const stored = {syncKey: "fake-key", latestCaptures: {canvas: {source: "canvas"}}};
  const calls = [];
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => stored,
                      set: async value => Object.assign(stored, value)}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: fn => { handlers.message = fn; }},
              onMessageExternal: {addListener: fn => { handlers.external = fn; }}},
    alarms: {create: () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async () => [{id: 3, status: "complete"}], create: async () => {}},
    scripting: {executeScript: async ({files}) => {
      calls.push(files[0]);
      setTimeout(() => handlers.message({type: "CAPTURE_READY", capture: {source: "canvas"}},
        {tab: {url: "https://canvas.ubc.ca/courses"}}, () => {}), 0);
    }}
  };
  const context = {chrome, URL, Date, JSON, setTimeout, clearTimeout,
    fetch: async (url) => {
      calls.push(url);
      return {ok: true, json: async () =>
        ({source: "canvas", stored: false, courses: [], items: []})};
    },
    HUB_PROVIDERS: [
      {id: "canvas", label: "Canvas", origin: "https://canvas.ubc.ca", captureFile: "providers/canvas.js"},
      {id: "piazza", label: "Piazza", origin: "https://piazza.com", captureFile: "providers/piazza.js"}
    ], importScripts: () => {}};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  const result = await new Promise(resolve => handlers.external({type: "SYNC_ALL"},
    {url: "https://hello-hacks26.vercel.app/"}, resolve));
  assert.equal(result.ok, true);
  assert.deepEqual(Array.from(result.results, r => [r.provider, r.ok]), [["canvas", true]]);
  assert.deepEqual(calls, ["providers/canvas.js", "https://hello-hacks26.vercel.app/api/normalize",
    "https://hello-hacks26.vercel.app/api/sync"]);
  const status = await new Promise(resolve => handlers.external({type: "SYNC_STATUS"},
    {url: "https://hello-hacks26.vercel.app/"}, resolve));
  assert.deepEqual(Array.from(status.results, r => [r.provider, r.state]), [["canvas", "done"]]);
});

test("SYNC_ALL reports a provider error when its signed-in tab is closed", async () => {
  const handlers = {};
  const stored = {syncKey: "fake-key", latestCaptures: {canvas: {source: "canvas"}}};
  const chrome = {
    storage: {local: {setAccessLevel: async () => {}, get: async () => stored,
                      set: async () => {}}},
    runtime: {onInstalled: {addListener: () => {}},
              onMessage: {addListener: () => {}},
              onMessageExternal: {addListener: fn => { handlers.external = fn; }}},
    alarms: {create: () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async () => [], create: async () => { throw Error("must not open tab"); }},
    scripting: {executeScript: async () => { throw Error("must not capture"); }}
  };
  const context = {chrome, URL, Date, JSON, setTimeout, clearTimeout,
    HUB_PROVIDERS: [{id: "canvas", label: "Canvas", origin: "https://canvas.ubc.ca",
      captureFile: "providers/canvas.js"}], importScripts: () => {}};
  vm.runInNewContext(fs.readFileSync(new URL("./background.js", import.meta.url), "utf8"), context);
  const result = await new Promise(resolve => handlers.external({type: "SYNC_ALL"},
    {url: "https://hello-hacks26.vercel.app/"}, resolve));
  assert.equal(result.results[0].ok, false);
  assert.match(result.results[0].error, /Open Canvas/);
});
