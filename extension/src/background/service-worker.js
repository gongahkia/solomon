import { classifyPostTone } from "./tonal-classifier.js";
import { classifyPostWithGateway } from "./gateway-classifier.js";
import {
  createClassifierRequest,
  createSkippedClassifierResponse,
  isNegativeRating,
  normalizeRating,
  validateClassifierResponse
} from "../shared/classifier-contract.js";

const DEFAULT_SETTINGS = {
  enabled: true,
  tonalClassifierEnabled: true,
  minimumConfidence: 0.75,
  factualRetrievalEnabled: false,
  classifierSource: "local",
  gatewayUrl: "",
  gatewayAccessToken: "",
  gatewayTimeoutMs: 8000
};

const STORAGE_KEYS = {
  settings: "decorumSettings",
  detectedPosts: "decorumDetectedPosts",
  noteLedger: "decorumNoteLedger"
};

const MAX_DETECTED_POSTS = 50;
const MAX_LEDGER_ENTRIES = 100;
let storageWriteQueue = Promise.resolve();

function enqueueStorageWrite(operation) {
  const nextWrite = storageWriteQueue.then(operation, operation);
  storageWriteQueue = nextWrite.catch(() => {});
  return nextWrite;
}

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

function clampGatewayTimeout(value) {
  const numericValue = Number(value);

  if (!Number.isFinite(numericValue)) {
    return DEFAULT_SETTINGS.gatewayTimeoutMs;
  }

  return Math.min(15000, Math.max(1000, numericValue));
}

function sanitizeSettings(settings) {
  const tonalClassifierEnabled =
    settings.tonalClassifierEnabled ?? settings.mockNotesEnabled ?? true;
  const classifierSource = settings.classifierSource === "gateway" ? "gateway" : "local";

  return {
    enabled: Boolean(settings.enabled),
    tonalClassifierEnabled: Boolean(tonalClassifierEnabled),
    minimumConfidence: clampConfidence(settings.minimumConfidence),
    factualRetrievalEnabled: Boolean(settings.factualRetrievalEnabled),
    classifierSource,
    gatewayUrl: String(settings.gatewayUrl ?? "").trim(),
    gatewayAccessToken: String(settings.gatewayAccessToken ?? "").trim(),
    gatewayTimeoutMs: clampGatewayTimeout(settings.gatewayTimeoutMs)
  };
}

function compactPost(post, sender) {
  const text = String(post?.text ?? "");

  return {
    id: String(post?.id ?? `decorum:${Date.now()}`),
    author: String(post?.author ?? ""),
    textPreview: text.slice(0, 280),
    text,
    url: String(post?.url ?? sender.tab?.url ?? ""),
    detectedAt: String(post?.detectedAt ?? new Date().toISOString()),
    tabId: sender.tab?.id ?? null
  };
}

async function recordDetectedPost(post, sender) {
  return enqueueStorageWrite(async () => {
    const { detectedPosts } = await getState();
    const nextPost = compactPost(post, sender);
    const withoutExisting = detectedPosts.filter((item) => item.id !== nextPost.id);

    await chrome.storage.local.set({
      decorumDetectedPosts: [nextPost, ...withoutExisting].slice(0, MAX_DETECTED_POSTS)
    });

    return nextPost;
  });
}

function compactLedgerEntry(message, sender) {
  const note = message.note ?? {};
  const post = message.post ?? {};
  const classification = message.classification ?? {};
  const compactedPost = compactPost(post, sender);

  return {
    traceId: String(note.traceId ?? `trace:${Date.now()}`),
    postId: compactedPost.id,
    kind: String(note.kind ?? "unknown"),
    label: String(note.label ?? "Context note"),
    reason: String(note.reason ?? ""),
    confidence: clampConfidence(note.confidence),
    dedupeKey: String(note.dedupeKey ?? ""),
    model: String(note.model ?? "unknown"),
    evidence: Array.isArray(note.evidence) ? note.evidence.slice(0, 5) : [],
    sources: Array.isArray(note.sources) ? note.sources.slice(0, 5) : [],
    postAuthor: compactedPost.author,
    postPreview: compactedPost.textPreview,
    postText: compactedPost.text,
    postUrl: compactedPost.url,
    shownAt: String(message.shownAt ?? new Date().toISOString()),
    request: classification.request ?? null,
    classifier: classification.classifier ?? null,
    decision: classification.decision ?? null,
    contractVersion: classification.contractVersion ?? null,
    responseId: classification.responseId ?? null,
    rating: null,
    ratedAt: null,
    ratingCategory: null,
    falsePositive: false
  };
}

async function recordShownNote(message, sender) {
  return enqueueStorageWrite(async () => {
    const { noteLedger } = await getState();
    const nextEntry = compactLedgerEntry(message, sender);
    const withoutExisting = noteLedger.filter((entry) => entry.traceId !== nextEntry.traceId);

    await chrome.storage.local.set({
      decorumNoteLedger: [nextEntry, ...withoutExisting].slice(0, MAX_LEDGER_ENTRIES)
    });

    return nextEntry;
  });
}

async function recordNoteRating(message) {
  return enqueueStorageWrite(async () => {
    const { noteLedger } = await getState();
    const rating = normalizeRating(message.rating);
    const ratedAt = String(message.ratedAt ?? new Date().toISOString());
    const traceId = String(message.traceId ?? "");

    const nextLedger = noteLedger.map((entry) =>
      entry.traceId === traceId
        ? {
            ...entry,
            rating,
            ratingCategory: rating,
            ratedAt,
            falsePositive: isNegativeRating(rating)
          }
        : entry
    );

    await chrome.storage.local.set({ decorumNoteLedger: nextLedger });
    return nextLedger.find((entry) => entry.traceId === traceId) ?? null;
  });
}

async function updateSettings(settings) {
  const currentState = await getState();
  const nextSettings = sanitizeSettings({
    ...currentState.settings,
    ...settings
  });

  await chrome.storage.local.set({ decorumSettings: nextSettings });
  await broadcastSettingsUpdated(nextSettings);
  return nextSettings;
}

async function broadcastSettingsUpdated(settings) {
  const tabs = await chrome.tabs.query({}).catch(() => []);

  await Promise.allSettled(
    tabs
      .filter((tab) => Number.isInteger(tab.id))
      .map((tab) =>
        chrome.tabs.sendMessage(tab.id, {
          type: "DECORUM_SETTINGS_UPDATED",
          settings
        })
      )
  );
}

async function classifyPost(post) {
  const { settings } = await getState();

  if (!settings.enabled) {
    return {
      note: null,
      skippedReason: "decorum_disabled"
    };
  }

  if (!settings.tonalClassifierEnabled) {
    const request = createClassifierRequest({ post, settings });
    return createSkippedClassifierResponse({
      request,
      skippedReason: "tonal_classifier_disabled"
    });
  }

  const request = createClassifierRequest({ post, settings });
  if (settings.classifierSource === "gateway") {
    return classifyPostWithGateway(request, {
      gatewayUrl: settings.gatewayUrl,
      accessToken: settings.gatewayAccessToken,
      timeoutMs: settings.gatewayTimeoutMs
    });
  }

  const response = classifyPostTone(request);
  const validation = validateClassifierResponse(response);

  if (!validation.ok) {
    console.warn("[decorum] Classifier response failed validation", validation.errors);
  }

  return response;
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

    case "DECORUM_CLASSIFY_POST":
      return classifyPost(message.post);

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

globalThis.DecorumBackground = {
  classifyPost,
  getState,
  updateSettings
};
