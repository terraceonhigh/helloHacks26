const DEFAULT_HUB_BASE = "https://hello-hacks26.vercel.app";
const key = document.querySelector("#key");
const hubBaseInput = document.querySelector("#hubBase");
const status = document.querySelector("#status");
const providerSelect = document.querySelector("#provider");
const originInput = document.querySelector("#origin");
for (const provider of globalThis.HUB_PROVIDERS) {
  const option = document.createElement("option");
  option.value = provider.id;
  option.textContent = provider.label;
  providerSelect.append(option);
}

function generateKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function refresh() {
  const saved = await chrome.storage.local.get(["syncKey", "syncStatus", "providerOrigins", "hubBase"]);
  if (!saved.syncKey) {
    // ponytail: a key is just a random client secret (hub/hosted.py) - generate
    // one by default so hosted sync works out of the box, same as visiting a
    // site for the first time. Shown in the field so the student can copy it
    // to use the same hub on another browser.
    saved.syncKey = generateKey();
    await chrome.storage.local.set({syncKey: saved.syncKey});
  }
  key.value = saved.syncKey;
  hubBaseInput.value = saved.hubBase || "";
  hubBaseInput.placeholder = DEFAULT_HUB_BASE;
  originInput.value = saved.providerOrigins?.[providerSelect.value] || "";
  originInput.hidden = !globalThis.HUB_PROVIDERS.find(p => p.id === providerSelect.value)?.customOrigin;
  status.textContent = saved.syncStatus
    || `Syncing to ${saved.hubBase || DEFAULT_HUB_BASE}. Sign in to the selected provider, then sync.`;
}
providerSelect.addEventListener("change", refresh);

// Pure so it's unit-testable without a DOM (matches the rest of this repo's
// "logic gets a test" standard) - given whatever a student typed, returns a
// real https:// origin or null. A wildcard hostname (e.g. "https://*" or
// "https://*.ubc.ca") survives the URL parser as origin "https://*" /
// "https://*.ubc.ca" verbatim - that string would otherwise go straight into
// chrome.permissions.request as an origin *pattern*, requesting every HTTPS
// site (or every ubc.ca subdomain) instead of the one site the student
// actually typed. Require a real dotted hostname, no wildcard, no port.
// Shared by both the sync-target field (#save) and the custom-provider
// origin field (#sync) - the same bug in either one hands out the same
// over-broad permission grant.
function parseCustomOrigin(value) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) return null;
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(parsed.hostname) || parsed.port) return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

document.querySelector("#save").addEventListener("click", async () => {
  let hubBase = "";
  if (hubBaseInput.value.trim()) {
    hubBase = parseCustomOrigin(hubBaseInput.value.trim());
    if (!hubBase) {
      status.textContent = "Enter a valid HTTPS sync target, e.g. https://hello-hacks26-one.vercel.app";
      return;
    }
    if (hubBase !== DEFAULT_HUB_BASE) {
      const granted = await chrome.permissions.request({origins: [`${hubBase}/*`]});
      if (!granted) {
        status.textContent = "Site access for the sync target was not granted.";
        return;
      }
    }
  }
  await chrome.storage.local.set({syncKey: key.value.trim(), hubBase});
  status.textContent = `Saved. Syncing to ${hubBase || DEFAULT_HUB_BASE}.`;
});

document.querySelector("#sync").addEventListener("click", async () => {
  status.textContent = "Starting sync…";
  const provider = globalThis.HUB_PROVIDERS.find(p => p.id === providerSelect.value);
  if (provider.customOrigin) {
    const origin = parseCustomOrigin(originInput.value);
    if (!origin) {
      status.textContent = "Enter the HTTPS address of your provider site.";
      return;
    }
    const granted = await chrome.permissions.request({origins: [`${origin}/*`]});
    if (!granted) {
      status.textContent = "Site access was not granted.";
      return;
    }
    const {providerOrigins = {}} = await chrome.storage.local.get("providerOrigins");
    providerOrigins[provider.id] = origin;
    await chrome.storage.local.set({providerOrigins});
  }
  const result = await chrome.runtime.sendMessage({type: "SYNC_NOW", provider: providerSelect.value});
  if (!result?.ok) status.textContent = result?.error || "Could not start sync";
  else setTimeout(refresh, 1000);
});
refresh();
