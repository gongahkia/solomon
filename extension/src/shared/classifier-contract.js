export const CLASSIFIER_CONTRACT_VERSION = "decorum.classifier.v1";
export const RUBRIC_VERSION = "tonal-rubric-2026-06-14";
export const LOCAL_CLASSIFIER_VERSION = "local-tonal-rules-v1";
export const SAFETY_COPY_VERSION = "safety-copy-v1";

export const NOTE_KINDS = [
  "engagement_bait",
  "humblebrag",
  "fake_vulnerability",
  "ai_ghostwritten",
  "corporate_cliche",
  "sycophancy",
  "waffle",
  "funding_announcement"
];

export const SKIPPED_REASONS = [
  "empty_post",
  "no_tonal_signal",
  "decorum_disabled",
  "tonal_classifier_disabled",
  "below_confidence_threshold",
  "gateway_unavailable",
  "gateway_response_invalid",
  "contract_validation_failed"
];

export const RATING_OPTIONS = [
  "helpful",
  "incorrect",
  "unfair_tone_read",
  "missing_context",
  "too_noisy"
];

export function stableHash(input) {
  let hash = 2166136261;

  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }

  return (hash >>> 0).toString(36);
}

export function normalizePostText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function requestIdFor(post, requestedAt) {
  return `req:${stableHash(`${post.id}:${post.text}:${requestedAt}`)}`;
}

export function createClassifierRequest({ post, settings, source = "extension" }) {
  const requestedAt = new Date().toISOString();
  const text = normalizePostText(post?.text);
  const normalizedPost = {
    id: String(post?.id ?? `decorum:${stableHash(text)}`),
    author: String(post?.author ?? ""),
    text,
    url: String(post?.url ?? ""),
    detectedAt: String(post?.detectedAt ?? requestedAt)
  };

  return {
    contractVersion: CLASSIFIER_CONTRACT_VERSION,
    requestId: requestIdFor(normalizedPost, requestedAt),
    requestedAt,
    source,
    rubricVersion: RUBRIC_VERSION,
    safetyCopyVersion: SAFETY_COPY_VERSION,
    capabilities: {
      tonal: Boolean(settings?.tonalClassifierEnabled ?? true),
      factual: Boolean(settings?.factualRetrievalEnabled ?? false)
    },
    settingsSnapshot: {
      minimumConfidence: Number(settings?.minimumConfidence ?? 0.75),
      tonalClassifierEnabled: Boolean(settings?.tonalClassifierEnabled ?? true),
      factualRetrievalEnabled: Boolean(settings?.factualRetrievalEnabled ?? false)
    },
    post: normalizedPost
  };
}

export function createTraceId({ requestId, postId, kind, generatedAt }) {
  const randomPart = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `trace:${stableHash(`${requestId}:${postId}:${kind}:${generatedAt}:${randomPart}`)}`;
}

export function validateClassifierRequest(request) {
  const errors = [];

  if (request?.contractVersion !== CLASSIFIER_CONTRACT_VERSION) {
    errors.push("unsupported_contract_version");
  }

  if (!request?.requestId) {
    errors.push("missing_request_id");
  }

  if (!request?.post?.id) {
    errors.push("missing_post_id");
  }

  if (typeof request?.post?.text !== "string") {
    errors.push("missing_post_text");
  }

  if (!Number.isFinite(Number(request?.settingsSnapshot?.minimumConfidence))) {
    errors.push("invalid_minimum_confidence");
  }

  return {
    ok: errors.length === 0,
    errors
  };
}

export function createSkippedClassifierResponse({ request, skippedReason, candidate = null, classifier = null }) {
  return {
    contractVersion: CLASSIFIER_CONTRACT_VERSION,
    requestId: request.requestId,
    responseId: `res:${stableHash(`${request.requestId}:${skippedReason}`)}`,
    generatedAt: new Date().toISOString(),
    classifier: classifier ?? {
      provider: "local",
      model: LOCAL_CLASSIFIER_VERSION,
      rubricVersion: request.rubricVersion,
      safetyCopyVersion: request.safetyCopyVersion
    },
    note: null,
    candidate,
    decision: {
      status: "skipped",
      skippedReason,
      threshold: request.settingsSnapshot.minimumConfidence
    },
    request
  };
}

export function createShownClassifierResponse({ request, note }) {
  return {
    contractVersion: CLASSIFIER_CONTRACT_VERSION,
    requestId: request.requestId,
    responseId: `res:${stableHash(`${request.requestId}:${note.traceId}`)}`,
    generatedAt: note.generatedAt,
    classifier: {
      provider: "local",
      model: note.model,
      rubricVersion: request.rubricVersion,
      safetyCopyVersion: request.safetyCopyVersion
    },
    note,
    candidate: note,
    decision: {
      status: "shown",
      skippedReason: null,
      threshold: request.settingsSnapshot.minimumConfidence
    },
    request
  };
}

export function validateClassifierResponse(response) {
  const errors = [];

  if (response?.contractVersion !== CLASSIFIER_CONTRACT_VERSION) {
    errors.push("unsupported_contract_version");
  }

  if (!response?.requestId) {
    errors.push("missing_request_id");
  }

  if (!["shown", "skipped"].includes(response?.decision?.status)) {
    errors.push("invalid_decision_status");
  }

  if (response?.decision?.status === "shown") {
    if (!response.note?.traceId) {
      errors.push("missing_trace_id");
    }

    if (!NOTE_KINDS.includes(response.note?.kind)) {
      errors.push("invalid_note_kind");
    }

    if (!Number.isFinite(Number(response.note?.confidence))) {
      errors.push("invalid_confidence");
    }
  }

  if (
    response?.decision?.status === "skipped" &&
    !SKIPPED_REASONS.includes(response?.decision?.skippedReason)
  ) {
    errors.push("invalid_skipped_reason");
  }

  return {
    ok: errors.length === 0,
    errors
  };
}

export function isNegativeRating(rating) {
  return ["incorrect", "unfair_tone_read", "too_noisy"].includes(rating);
}

export function normalizeRating(value) {
  return RATING_OPTIONS.includes(value) ? value : "helpful";
}
