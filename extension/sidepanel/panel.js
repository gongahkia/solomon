const DEFAULT_STATE = {
  settings: {
    enabled: true,
    tonalClassifierEnabled: true,
    minimumConfidence: 0.75
  },
  detectedPosts: [],
  noteLedger: []
};

const elements = {
  statusMessage: document.querySelector("#status-message"),
  enabledInput: document.querySelector("#enabled-input"),
  mockNotesInput: document.querySelector("#mock-notes-input"),
  confidenceInput: document.querySelector("#confidence-input"),
  confidenceOutput: document.querySelector("#confidence-output"),
  detectedSummary: document.querySelector("#detected-summary"),
  detectedList: document.querySelector("#detected-list"),
  ledgerSummary: document.querySelector("#ledger-summary"),
  ledgerList: document.querySelector("#ledger-list"),
  clearLedgerButton: document.querySelector("#clear-ledger-button")
};

let currentState = DEFAULT_STATE;
let confidenceWriteTimer = null;

function formatConfidence(value) {
  return `${Math.round(value * 100)}%`;
}

function formatTime(value) {
  if (!value) {
    return "unknown time";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

async function sendMessage(message) {
  const response = await chrome.runtime.sendMessage(message);

  if (!response?.ok) {
    throw new Error(response?.error ?? "Request failed");
  }

  return response;
}

function renderSettings(settings) {
  elements.enabledInput.checked = settings.enabled;
  elements.mockNotesInput.checked = settings.tonalClassifierEnabled;
  elements.confidenceInput.value = String(Math.round(settings.minimumConfidence * 100));
  elements.confidenceOutput.textContent = formatConfidence(settings.minimumConfidence);
  elements.statusMessage.textContent = settings.enabled ? "Enabled" : "Disabled";
}

function renderDetectedPosts(posts) {
  elements.detectedSummary.textContent = `${posts.length} seen`;
  elements.detectedList.replaceChildren();

  if (posts.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "No posts detected yet.";
    elements.detectedList.append(empty);
    return;
  }

  for (const post of posts.slice(0, 5)) {
    const item = document.createElement("li");

    const title = document.createElement("p");
    title.className = "item-title";
    title.textContent = post.author || "Unknown author";

    const meta = document.createElement("p");
    meta.className = "item-meta";
    meta.textContent = formatTime(post.detectedAt);

    const copy = document.createElement("p");
    copy.className = "item-copy";
    copy.textContent = post.textPreview || post.id;

    item.append(title, meta, copy);
    elements.detectedList.append(item);
  }
}

function renderLedger(entries) {
  const falsePositiveCount = entries.filter((entry) => entry.falsePositive).length;
  elements.ledgerSummary.textContent = `${entries.length} notes shown, ${falsePositiveCount} false positives`;
  elements.ledgerList.replaceChildren();

  if (entries.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "No notes shown yet.";
    elements.ledgerList.append(empty);
    return;
  }

  for (const entry of entries.slice(0, 10)) {
    const item = document.createElement("li");

    const title = document.createElement("p");
    title.className = "item-title";
    title.textContent = entry.falsePositive ? `False positive: ${entry.label}` : entry.label;

    const meta = document.createElement("p");
    meta.className = "item-meta";
    meta.textContent = `${formatConfidence(entry.confidence)} confidence · ${formatTime(entry.shownAt)}`;

    const copy = document.createElement("p");
    copy.className = "item-copy";
    copy.textContent = entry.reason || entry.traceId;

    item.append(title, meta, copy);
    elements.ledgerList.append(item);
  }
}

function render(state) {
  currentState = {
    ...DEFAULT_STATE,
    ...state,
    settings: {
      ...DEFAULT_STATE.settings,
      ...state.settings
    }
  };

  renderSettings(currentState.settings);
  renderDetectedPosts(currentState.detectedPosts);
  renderLedger(currentState.noteLedger);
}

async function loadState() {
  const response = await sendMessage({ type: "DECORUM_GET_STATE" });
  render(response);
}

async function updateSettings(partialSettings) {
  const response = await sendMessage({
    type: "DECORUM_UPDATE_SETTINGS",
    settings: {
      ...currentState.settings,
      ...partialSettings
    }
  });

  render({
    ...currentState,
    settings: response.settings
  });
}

elements.enabledInput.addEventListener("change", () => {
  updateSettings({ enabled: elements.enabledInput.checked }).catch((error) => {
    console.error("[decorum] Failed to update enabled setting", error);
  });
});

elements.mockNotesInput.addEventListener("change", () => {
  updateSettings({ tonalClassifierEnabled: elements.mockNotesInput.checked }).catch((error) => {
    console.error("[decorum] Failed to update tonal classifier setting", error);
  });
});

elements.confidenceInput.addEventListener("input", () => {
  const minimumConfidence = Number(elements.confidenceInput.value) / 100;
  elements.confidenceOutput.textContent = formatConfidence(minimumConfidence);

  if (confidenceWriteTimer) {
    window.clearTimeout(confidenceWriteTimer);
  }

  confidenceWriteTimer = window.setTimeout(() => {
    updateSettings({ minimumConfidence }).catch((error) => {
      console.error("[decorum] Failed to update confidence setting", error);
    });
  }, 200);
});

elements.clearLedgerButton.addEventListener("click", () => {
  sendMessage({ type: "DECORUM_CLEAR_LEDGER" })
    .then(() =>
      render({
        ...currentState,
        noteLedger: []
      })
    )
    .catch((error) => {
      console.error("[decorum] Failed to clear ledger", error);
    });
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (
    areaName === "local" &&
    (changes.decorumSettings || changes.decorumDetectedPosts || changes.decorumNoteLedger)
  ) {
    loadState().catch((error) => {
      console.error("[decorum] Failed to refresh panel state", error);
    });
  }
});

loadState().catch((error) => {
  elements.statusMessage.textContent = "Unavailable";
  console.error("[decorum] Failed to render panel", error);
});
