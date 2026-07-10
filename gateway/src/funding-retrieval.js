import {
  CLASSIFIER_CONTRACT_VERSION,
  SAFETY_COPY_VERSION,
  createSkippedClassifierResponse,
  createTraceId,
  stableHash
} from "../../extension/src/shared/classifier-contract.js";

export const EXA_SEARCH_URL = "https://api.exa.ai/search";
export const FUNDING_RETRIEVAL_VERSION = "exa-funding-search-v1";
const FUNDING_CONFIDENCE = 0.84;

const FUNDING_PATTERNS = [
  /\b(raised|raises|secured|closed|announced)\s+(?:a\s+)?(?:[$\u20ac\u00a3]\s?\d+(?:\.\d+)?\s?(?:m|million|b|billion)|\d+(?:\.\d+)?\s?(?:m|million|b|billion))\b/i,
  /\b(series\s+[a-h]|seed|pre-seed|preseed)\s+(?:round|funding|financing)\b/i,
  /\b(?:[$\u20ac\u00a3]\s?\d+(?:\.\d+)?\s?(?:m|million|b|billion)|\d+(?:\.\d+)?\s?(?:m|million|b|billion))\s+(?:series\s+[a-h]|seed|pre-seed|preseed)\b/i
];

function compactWhitespace(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function clip(value, maxLength = 220) {
  const text = compactWhitespace(value);
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

export function detectFundingAnnouncementClaim(request) {
  if (!request?.capabilities?.factual || !request?.settingsSnapshot?.factualRetrievalEnabled) {
    return null;
  }

  const text = compactWhitespace(request.post?.text);

  if (!text) {
    return null;
  }

  const evidence = FUNDING_PATTERNS.map((pattern) => text.match(pattern)?.[0]).filter(Boolean);

  if (evidence.length === 0) {
    return null;
  }

  return {
    kind: "funding_announcement",
    confidence: 0.86,
    query: `${text} funding announcement official source`,
    evidence: [...new Set(evidence)].slice(0, 4)
  };
}

export function buildExaFundingSearchRequest(claim) {
  return {
    query: claim.query,
    type: "fast",
    category: "news",
    numResults: 5,
    contents: {
      highlights: true,
      summary: true
    },
    systemPrompt:
      "Prefer official company announcements, investor posts, reputable business news, SEC filings, and primary sources. Avoid duplicate syndicated pages."
  };
}

function normalizeExaSource(result, providerRequestId) {
  const url = String(result?.url ?? "");

  return {
    provider: "exa",
    providerRequestId,
    title: String(result?.title ?? url ?? "Untitled source"),
    url,
    publishedDate: result?.publishedDate ?? null,
    excerpt: clip(result?.highlights?.[0] ?? result?.summary ?? result?.text ?? "")
  };
}

export async function searchFundingContextWithExa({ request, apiKey, fetchImpl = fetch }) {
  const claim = detectFundingAnnouncementClaim(request);

  if (!claim || !apiKey) {
    return {
      claim,
      confidence: 0,
      sources: [],
      evidence: claim?.evidence ?? []
    };
  }

  const payload = buildExaFundingSearchRequest(claim);
  const response = await fetchImpl(EXA_SEARCH_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey
    },
    body: JSON.stringify(payload)
  });

  if (!response?.ok) {
    return {
      claim,
      confidence: 0,
      sources: [],
      evidence: claim.evidence,
      providerRequestId: null
    };
  }

  const data = await response.json();
  const sources = (data.results ?? [])
    .map((result) => normalizeExaSource(result, data.requestId ?? null))
    .filter((source) => /^https?:\/\//i.test(source.url))
    .slice(0, 3);

  return {
    claim,
    confidence: sources.length >= 2 ? FUNDING_CONFIDENCE : 0.78,
    sources,
    evidence: claim.evidence,
    providerRequestId: data.requestId ?? null
  };
}

export function createFundingContextResponse({ request, retrieval, generatedAt = new Date().toISOString() }) {
  if (!retrieval?.claim) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "no_tonal_signal"
    });
  }

  const note = {
    traceId: createTraceId({
      requestId: request.requestId,
      postId: request.post.id,
      kind: "funding_announcement",
      generatedAt
    }),
    dedupeKey: `post:${stableHash(`${request.post.id}:funding_announcement`)}`,
    kind: "funding_announcement",
    label: "Funding context",
    reason:
      "This post makes a funding-announcement claim. These sources can help verify the round, amount, and parties involved.",
    confidence: retrieval.confidence,
    model: FUNDING_RETRIEVAL_VERSION,
    evidence: retrieval.evidence.slice(0, 4),
    sources: retrieval.sources,
    generatedAt
  };

  if (note.confidence < request.settingsSnapshot.minimumConfidence || note.sources.length === 0) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "below_confidence_threshold",
      candidate: note,
      classifier: {
        provider: "gateway",
        model: FUNDING_RETRIEVAL_VERSION,
        rubricVersion: request.rubricVersion,
        safetyCopyVersion: request.safetyCopyVersion ?? SAFETY_COPY_VERSION
      }
    });
  }

  return {
    contractVersion: CLASSIFIER_CONTRACT_VERSION,
    requestId: request.requestId,
    responseId: `res:${stableHash(`${request.requestId}:${note.traceId}`)}`,
    generatedAt,
    classifier: {
      provider: "gateway",
      model: FUNDING_RETRIEVAL_VERSION,
      rubricVersion: request.rubricVersion,
      safetyCopyVersion: request.safetyCopyVersion ?? SAFETY_COPY_VERSION
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

export function attachFundingContextToClassification({ classification, retrieval }) {
  if (
    !classification?.note ||
    !retrieval?.sources?.length ||
    retrieval.confidence < classification.decision.threshold
  ) {
    return classification;
  }

  return {
    ...classification,
    note: {
      ...classification.note,
      evidence: [...new Set([...(classification.note.evidence ?? []), ...retrieval.evidence])].slice(0, 6),
      sources: retrieval.sources
    },
    candidate: classification.candidate
      ? {
          ...classification.candidate,
          sources: retrieval.sources
        }
      : classification.candidate
  };
}
