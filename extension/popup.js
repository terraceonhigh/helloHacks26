const key = document.querySelector("#key");
const status = document.querySelector("#status");
const providerSelect = document.querySelector("#provider");
const originInput = document.querySelector("#origin");
for (const provider of globalThis.HUB_PROVIDERS) {
  const option = document.createElement("option");
  option.value = provider.id;
  option.textContent = provider.label;
  providerSelect.append(option);
}

async function refresh() {
  const saved = await chrome.storage.local.get(["syncKey", "syncStatus", "providerOrigins"]);
  key.value = saved.syncKey || "";
  originInput.value = saved.providerOrigins?.[providerSelect.value] || "";
  originInput.hidden = !globalThis.HUB_PROVIDERS.find(p => p.id === providerSelect.value)?.customOrigin;
  status.textContent = saved.syncStatus || "Sign in to the selected provider, then sync.";
}
providerSelect.addEventListener("change", refresh);

document.querySelector("#save").addEventListener("click", async () => {
  await chrome.storage.local.set({syncKey: key.value.trim()});
  status.textContent = "Sync key saved on this browser.";
});
document.querySelector("#sync").addEventListener("click", async () => {
  status.textContent = "Starting sync…";
  const provider = globalThis.HUB_PROVIDERS.find(p => p.id === providerSelect.value);
  if (provider.customOrigin) {
    let origin;
    try {
      const parsed = new URL(originInput.value);
      if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) throw Error();
      origin = parsed.origin;
    } catch {
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
