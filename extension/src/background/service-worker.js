const DEFAULT_SETTINGS = {
  enabled: true,
  mockNotesEnabled: false,
  minimumConfidence: 0.75
};

async function ensureDefaults() {
  const { decorumSettings } = await chrome.storage.local.get("decorumSettings");

  if (!decorumSettings) {
    await chrome.storage.local.set({ decorumSettings: DEFAULT_SETTINGS });
    return;
  }

  await chrome.storage.local.set({
    decorumSettings: {
      ...DEFAULT_SETTINGS,
      ...decorumSettings
    }
  });
}

chrome.runtime.onInstalled.addListener(() => {
  ensureDefaults().catch((error) => {
    console.error("[decorum] Failed to initialize settings", error);
  });
});

chrome.runtime.onStartup.addListener(() => {
  ensureDefaults().catch((error) => {
    console.error("[decorum] Failed to initialize settings", error);
  });
});

chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: true })
  .catch((error) => console.error("[decorum] Failed to set side panel behavior", error));
