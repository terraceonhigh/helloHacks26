importScripts("providers.js");
const DEFAULT_HUB_BASE = "https://hello-hacks26.vercel.app";
const PROVIDERS = globalThis.HUB_PROVIDERS;
const pendingCaptures = new Map();
let syncProgress = [];

async function hubBase() {
  const {hubBase: base} = await chrome.storage.local.get("hubBase");
  return base || DEFAULT_HUB_BASE;
}

// The upload key stays in trusted extension contexts, never in a Canvas page.
chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});

async function setStatus(message) {
  await chrome.storage.local.set({syncStatus: message});
}

async function saveCapture(provider, capture) {
  const {latestCaptures = {}} = await chrome.storage.local.get("latestCaptures");
  latestCaptures[provider.id] = capture;
  await chrome.storage.local.set({latestCaptures});
  const base = await hubBase();
  const normalized = await fetch(`${base}/api/normalize`, {
    method: "POST", redirect: "error",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(capture)
  });
  if (!normalized.ok) throw new Error(`Lauds normalization failed (${normalized.status})`);
  const model = await normalized.json();
  if (model.source !== provider.id || model.stored !== false
      || !Array.isArray(model.courses) || !Array.isArray(model.items)) {
    throw new Error("Lauds returned an invalid normalized capture");
  }
  const {latestModels = {}} = await chrome.storage.local.get("latestModels");
  latestModels[provider.id] = model;
  await chrome.storage.local.set({latestModels});
  const {syncKey} = await chrome.storage.local.get("syncKey");
  if (!syncKey) {
    // The popup generates a key by default; this only fires if it was cleared.
    await setStatus(`${provider.label} normalized by Vercel and saved locally. No sync key saved - open the popup to generate one.`);
    return;
  }
  const response = await fetch(`${base}/api/sync`, {
    method: "POST", redirect: "error",
    headers: {"Content-Type": "application/json", Authorization: `Bearer ${syncKey}`},
    body: JSON.stringify(model)
  });
  if (!response.ok) throw new Error(`Lauds upload failed (${response.status})`);
  await setStatus(`${provider.label} uploaded at ${new Date().toLocaleString()}`);
}

async function navigateTab(tabId, url) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("Provider page took too long to load"));
    }, 20000);
    function onUpdated(changedId, changeInfo, tab) {
      if (changedId !== tabId || changeInfo.status !== "complete") return;
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(tab);
    }
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.update(tabId, {url}).catch(error => {
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(error);
    });
  });
}

async function captureNavigated(provider, tabId, origin) {
  const home = await navigateTab(tabId, `${origin}/`);
  if (new URL(home.url).origin !== origin) throw new Error(`Sign in to ${provider.label} first`);
  const [{result: index}] = await chrome.scripting.executeScript({
    target: {tabId}, files: [provider.indexFile]
  });
  if (!Array.isArray(index) || index.length > 100) throw new Error("Invalid provider course index");
  const courses = [];
  for (const course of index) {
    const courseId = course[provider.courseIdField];
    if (typeof courseId !== "string" || !provider.courseIdPattern.test(courseId)
        || typeof course.title !== "string") {
      throw new Error("Invalid provider course link");
    }
    const path = provider.pagePathTemplate.replace("{id}", encodeURIComponent(courseId));
    const page = await navigateTab(tabId, `${origin}${path}`);
    if (new URL(page.url).origin !== origin || new URL(page.url).pathname !== path) {
      throw new Error(`Could not open ${provider.label} assessments`);
    }
    const [{result: detail}] = await chrome.scripting.executeScript({
      target: {tabId}, files: [provider.pageFile]
    });
    if (detail?.[provider.courseIdField] !== courseId
        || !Array.isArray(detail[provider.rowsKey])) {
      throw new Error("Invalid provider assessments page");
    }
    courses.push({...course, [provider.rowsKey]: detail[provider.rowsKey]});
  }
  const capture = {source: provider.id, origin, courses};
  if (JSON.stringify(capture).length > 1_000_000) throw new Error("Provider capture exceeds the sync limit");
  await saveCapture(provider, capture);
}

async function syncNow(providerId, interactive = true, awaitUpload = false) {
  const provider = PROVIDERS.find(p => p.id === providerId);
  if (!provider) throw new Error("This provider has no verified extension adapter");
  if (!interactive && provider.indexFile) return; // Navigation is manual so a timer never moves a student's tab.
  const {providerOrigins = {}} = await chrome.storage.local.get("providerOrigins");
  const origin = provider.customOrigin ? providerOrigins[provider.id] : provider.origin;
  if (!origin) {
    if (awaitUpload) throw new Error(`Set the ${provider.label} site URL in the extension popup`);
    if (interactive) await setStatus(`Enter your ${provider.label} site URL in the extension popup.`);
    return;
  }
  const tabs = await chrome.tabs.query({url: `${origin}/*`});
  const tab = tabs.find(t => t.status === "complete" && t.id);
  if (!tab) {
    if (awaitUpload) throw new Error(`Open ${provider.label}, sign in, then sync again`);
    if (interactive) {
      await chrome.tabs.create({url: `${origin}/`});
      await setStatus(`${provider.label} opened. Sign in there, then press Sync again.`);
    }
    return;
  }
  await setStatus(`Reading ${provider.label} tasks…`);
  if (provider.indexFile && provider.pageFile) {
    await captureNavigated(provider, tab.id, origin);
    return;
  }
  if (provider.pageSessionPath) {
    const [{result: pageSessionValue}] = await chrome.scripting.executeScript({
      target: {tabId: tab.id}, world: "MAIN",
      func: path => path.reduce((value, key) => value?.[key], globalThis),
      args: [provider.pageSessionPath]
    });
    if (typeof pageSessionValue !== "string" || !/^[a-zA-Z0-9]{6,128}$/.test(pageSessionValue)) {
      throw new Error(`${provider.label} session key unavailable. Sign in and reopen its dashboard.`);
    }
    await chrome.scripting.executeScript({target: {tabId: tab.id},
      func: key => { globalThis.__hubPageSessionValue = key; }, args: [pageSessionValue]});
  }
  if (!awaitUpload) {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: [provider.captureFile]});
    return;
  }
  // DOM captures reply asynchronously through CAPTURE_READY/FAILED after injection.
  const uploaded = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingCaptures.delete(provider.id);
      reject(new Error(`${provider.label} capture timed out`));
    }, 60000);
    pendingCaptures.set(provider.id, {resolve, reject, timeout});
  });
  uploaded.catch(() => {});
  try {
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: [provider.captureFile]});
  } catch (error) {
    clearTimeout(pendingCaptures.get(provider.id)?.timeout);
    pendingCaptures.delete(provider.id);
    throw error;
  }
  await uploaded;
}

async function syncAll() {
  const {latestCaptures = {}, providerOrigins = {}, syncKey} = await chrome.storage.local.get(
    ["latestCaptures", "providerOrigins", "syncKey"]);
  if (!syncKey) throw new Error("Open the extension popup to set a hub sync key");
  const results = [];
  syncProgress = PROVIDERS.filter(provider => latestCaptures[provider.id]
    && (!provider.customOrigin || providerOrigins[provider.id]))
    .map(provider => ({provider: provider.id, label: provider.label, state: "pending"}));
  for (const provider of PROVIDERS) {
    if (!latestCaptures[provider.id] || provider.customOrigin && !providerOrigins[provider.id]) continue;
    const progress = syncProgress.find(row => row.provider === provider.id);
    progress.state = "running";
    try {
      await syncNow(provider.id, true, true);
      results.push({provider: provider.id, label: provider.label, ok: true});
      progress.state = "done";
    } catch (error) {
      results.push({provider: provider.id, label: provider.label, ok: false, error: error.message});
      progress.state = "done";
      progress.error = error.message;
    }
  }
  return results;
}

function finishCapture(providerId, error) {
  const pending = pendingCaptures.get(providerId);
  if (!pending) return;
  clearTimeout(pending.timeout);
  pendingCaptures.delete(providerId);
  if (error) pending.reject(error);
  else pending.resolve();
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("provider-sync", {periodInMinutes: 30});
});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "provider-sync") {
    for (const provider of PROVIDERS) {
      syncNow(provider.id, false).catch(error => setStatus(error.message));
    }
  }
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type === "SYNC_NOW") {
    syncNow(message.provider).then(() => respond({ok: true}), error => {
      setStatus(error.message);
      respond({ok: false, error: error.message});
    });
    return true;
  }
  if (message?.type !== "CAPTURE_READY" && message?.type !== "CAPTURE_FAILED") return;
  const providerId = message.type === "CAPTURE_READY" ? message.capture?.source : message.source;
  const provider = PROVIDERS.find(p => p.id === providerId);
  if (!provider || !sender.tab?.url) return;
  const senderOrigin = new URL(sender.tab.url).origin;
  (async () => {
    const {providerOrigins = {}} = await chrome.storage.local.get("providerOrigins");
    const allowedOrigin = provider.customOrigin ? providerOrigins[provider.id] : provider.origin;
    if (senderOrigin !== allowedOrigin || message.capture?.origin && message.capture.origin !== allowedOrigin) return;
    if (message.type === "CAPTURE_FAILED") {
      await setStatus(message.error || `${provider.label} sync failed`);
      finishCapture(provider.id, new Error(message.error || `${provider.label} sync failed`));
      return;
    }
    await saveCapture(provider, message.capture);
    finishCapture(provider.id);
  })().catch(error => {
    setStatus(error.message);
    finishCapture(provider.id, error);
  });
});

chrome.runtime.onMessageExternal.addListener((message, sender, respond) => {
  if (message?.type !== "SYNC_ALL" && message?.type !== "SYNC_STATUS") return;
  const origin = sender.url && new URL(sender.url).origin;
  if (!["https://hello-hacks26.vercel.app", "https://hello-hacks26-terraceonhigh.vercel.app",
        "http://localhost:3000"].includes(origin)) return;
  if (message.type === "SYNC_STATUS") {
    respond({results: syncProgress});
    return;
  }
  (async () => {
    const base = await hubBase();
    if (origin !== "http://localhost:3000" && origin !== base) {
      throw new Error(`Extension sync target is ${base}. Set it to ${origin} in the popup first.`);
    }
    return syncAll();
  })().then(results => respond({ok: true, results}), error =>
    respond({ok: false, error: error.message}));
  return true;
});
