import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

// popup.js runs top-level DOM wiring on load (querySelector, addEventListener,
// refresh()) - a minimal fake document/chrome lets it load without throwing,
// so parseCustomOrigin can be pulled out of the same vm context and called
// directly, same pattern as background.test.mjs.
function loadPopup() {
  const elements = {};
  const fakeElement = () => ({
    value: "", hidden: false, textContent: "",
    addEventListener: () => {}, append: () => {},
  });
  const document = {
    querySelector: (sel) => elements[sel] ??= fakeElement(),
    createElement: () => ({}),
  };
  const chrome = {
    storage: {local: {get: async () => ({}), set: async () => {}}},
    runtime: {sendMessage: async () => ({ok: true})},
    permissions: {request: async () => true},
  };
  const context = {document, chrome, HUB_PROVIDERS: [], URL, setTimeout};
  context.globalThis = context;
  vm.runInNewContext(fs.readFileSync(new URL("./popup.js", import.meta.url), "utf8"), context);
  return context;
}

test("parseCustomOrigin accepts a real HTTPS origin and strips its path", () => {
  const {parseCustomOrigin} = loadPopup();
  assert.equal(parseCustomOrigin("https://moodle.example.edu/some/path"), "https://moodle.example.edu");
});

test("parseCustomOrigin rejects a bare wildcard host (would request every HTTPS site)", () => {
  const {parseCustomOrigin} = loadPopup();
  assert.equal(parseCustomOrigin("https://*"), null);
});

test("parseCustomOrigin rejects a wildcard subdomain (would request every ubc.ca site)", () => {
  const {parseCustomOrigin} = loadPopup();
  assert.equal(parseCustomOrigin("https://*.ubc.ca"), null);
});

test("parseCustomOrigin rejects non-https and a custom port", () => {
  const {parseCustomOrigin} = loadPopup();
  assert.equal(parseCustomOrigin("http://moodle.example.edu"), null);
  assert.equal(parseCustomOrigin("https://moodle.example.edu:8443"), null);
});
