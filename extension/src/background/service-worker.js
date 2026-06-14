const DEFAULT_SETTINGS = {
  enabled: true,
  mockNotesEnabled: true,
  minimumConfidence: 0.75
};

const STORAGE_KEYS = {
  settings: "decorumSettings",
  detectedPosts: "decorumDetectedPosts",
  noteLedger: "decorumNoteLedger"
};

const MAX_DETECTED_POSTS = 50;
const MAX_LEDGER_ENTRIES = 100;

async function ensureDefaults() {
  const { decorumSettings, decorumDetectedPosts, decorumNoteLedger } =
    await chrome.storage.local.get(Object.values(STORAGE_KEYS));

  if (!decorumSettings) {
    await chrome.storage.local.set({ decorumSettings: DEFAULT_SETTINGS });
  } else {
    await chrome.storage.local.set({
      decorumSettings: {
        ...DEFAULT_SETTINGS,
        ...decorumSettings
      }
    });
  }

  if (!Array.isArray(decorumDetectedPosts)) {
    await chrome.storage.local.set({ decorumDetectedPosts: [] });
  }

  if (!Array.isArray(decorumNoteLedger)) {
    await chrome.storage.local.set({ decorumNoteLedger: [] });
  }
}

async function getState() {
  await ensureDefaults();

  const { decorumSettings, decorumDetectedPosts, decorumNoteLedger } =
    await chrome.storage.local.get(Object.values(STORAGE_KEYS));

  return {
    settings: {
      ...DEFAULT_SETTINGS,
      ...decorumSettings
    },
    detectedPosts: Array.isArray(decorumDetectedPosts) ? decorumDetectedPosts : [],
    noteLedger: Array.isArray(decorumNoteLedger) ? decorumNoteLedger : []
  };
}

function clampConfidence(value) {
  const numericValue = Number(value);

  if (!Number.isFinite(numericValue)) {
    return DEFAULT_SETTINGS.minimumConfidence;
  }

  return Math.min(0.99, Math.max(0.5, numericValue));
}

function sanitizeSettings(settings) {
  return {
    enabled: Boolean(settings.enabled),
    mockNotesEnabled: Boolean(settings.mockNotesEnabled),
    minimumConfidence: clampConfidence(settings.minimumConfidence)
  };
}

function compactPost(post, sender) {
  const text = String(post?.text ?? "");

  return {
    id: String(post?.id ?? `decorum:${Date.now()}`),
    author: String(post?.author ?? ""),
    textPreview: text.slice(0, 280),
    url: String(post?.url ?? sender.tab?.url ?? ""),
    detectedAt: String(post?.detectedAt ?? new Date().toISOString()),
    tabId: sender.tab?.id ?? null
  };
}

async function recordDetectedPost(post, sender) {
  const { detectedPosts } = await getState();
  const nextPost = compactPost(post, sender);
  const withoutExisting = detectedPosts.filter((item) => item.id !== nextPost.id);

  await chrome.storage.local.set({
    decorumDetectedPosts: [nextPost, ...withoutExisting].slice(0, MAX_DETECTED_POSTS)
  });

  return nextPost;
}

function compactLedgerEntry(message, sender) {
  const note = message.note ?? {};
  const post = message.post ?? {};
  const compactedPost = compactPost(post, sender);

  return {
    traceId: String(note.traceId ?? `trace:${Date.now()}`),
    postId: compactedPost.id,
    kind: String(note.kind ?? "unknown"),
    label: String(note.label ?? "Context note"),
    reason: String(note.reason ?? ""),
    confidence: clampConfidence(note.confidence),
    model: String(note.model ?? "unknown"),
    sources: Array.isArray(note.sources) ? note.sources.slice(0, 5) : [],
    postAuthor: compactedPost.author,
    postPreview: compactedPost.textPreview,
    postUrl: compactedPost.url,
    shownAt: String(message.shownAt ?? new Date().toISOString()),
    rating: null,
    ratedAt: null,
    falsePositive: false
  };
}

async function recordShownNote(message, sender) {
  const { noteLedger } = await getState();
  const nextEntry = compactLedgerEntry(message, sender);
  const withoutExisting = noteLedger.filter((entry) => entry.traceId !== nextEntry.traceId);

  await chrome.storage.local.set({
    decorumNoteLedger: [nextEntry, ...withoutExisting].slice(0, MAX_LEDGER_ENTRIES)
  });

  return nextEntry;
}

async function recordNoteRating(message) {
  const { noteLedger } = await getState();
  const rating = message.rating === "not_helpful" ? "not_helpful" : "helpful";
  const ratedAt = String(message.ratedAt ?? new Date().toISOString());
  const traceId = String(message.traceId ?? "");

  const nextLedger = noteLedger.map((entry) =>
    entry.traceId === traceId
      ? {
          ...entry,
          rating,
          ratedAt,
          falsePositive: rating === "not_helpful"
        }
      : entry
  );

  await chrome.storage.local.set({ decorumNoteLedger: nextLedger });
  return nextLedger.find((entry) => entry.traceId === traceId) ?? null;
}

async function updateSettings(settings) {
  const currentState = await getState();
  const nextSettings = sanitizeSettings({
    ...currentState.settings,
    ...settings
  });

  await chrome.storage.local.set({ decorumSettings: nextSettings });
  return nextSettings;
}

async function handleMessage(message, sender) {
  switch (message?.type) {
    case "DECORUM_GET_STATE":
      return getState();

    case "DECORUM_UPDATE_SETTINGS":
      return {
        settings: await updateSettings(message.settings ?? {})
      };

    case "DECORUM_POST_DETECTED":
      return {
        post: await recordDetectedPost(message.post, sender)
      };

    case "DECORUM_NOTE_SHOWN":
      return {
        entry: await recordShownNote(message, sender)
      };

    case "DECORUM_NOTE_RATED":
      return {
        entry: await recordNoteRating(message)
      };

    case "DECORUM_CLEAR_LEDGER":
      await chrome.storage.local.set({ decorumNoteLedger: [] });
      return { noteLedger: [] };

    default:
      return { ignored: true };
  }
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then((response) => sendResponse({ ok: true, ...response }))
    .catch((error) => {
      console.error("[decorum] Message handling failed", error);
      sendResponse({
        ok: false,
        error: error.message
      });
    });

  return true;
});
