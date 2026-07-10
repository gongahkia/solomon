import {
  NOTE_KINDS,
  createSkippedClassifierResponse,
  validateClassifierResponse
} from "../../extension/src/shared/classifier-contract.js";
import {
  attachFundingContextToClassification,
  createFundingContextResponse,
  searchFundingContextWithExa
} from "./funding-retrieval.js";

export const ANTHROPIC_TONAL_MODELS = {
  firstPass: "claude-haiku-4-5",
  borderline: "claude-sonnet-5"
};

export const BORDERLINE_CONFIDENCE_MARGIN = 0.06;
export const ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages";
export const ANTHROPIC_VERSION = "2023-06-01";

const OUTPUT_SCHEMA = {
  contractVersion: "decorum.classifier.v1",
  requestId: "string",
  responseId: "string",
  generatedAt: "ISO-8601 string",
  classifier: {
    provider: "gateway",
    model: "string",
    rubricVersion: "string",
    safetyCopyVersion: "string"
  },
  note: "null or note object",
  candidate: "null or best candidate note object",
  decision: {
    status: "shown or skipped",
    skippedReason: "null or skipped reason",
    threshold: "number"
  },
  request: "original request object"
};

export function isBorderlineTonalDecision(classification, threshold) {
  const confidence = Number(classification?.candidate?.confidence ?? classification?.note?.confidence);
  const minimumConfidence = Number(threshold ?? classification?.decision?.threshold);

  return (
    Number.isFinite(confidence) &&
    Number.isFinite(minimumConfidence) &&
    Math.abs(confidence - minimumConfidence) <= BORDERLINE_CONFIDENCE_MARGIN
  );
}

export function selectAnthropicTonalModel({ pass, classification, threshold } = {}) {
  if (pass === "borderline" || isBorderlineTonalDecision(classification, threshold)) {
    return ANTHROPIC_TONAL_MODELS.borderline;
  }

  return ANTHROPIC_TONAL_MODELS.firstPass;
}

function stableRubricPrompt(request) {
  return [
    "You classify LinkedIn post tone for Decorum.",
    `Contract: ${request.contractVersion}`,
    `Rubric: ${request.rubricVersion}`,
    `Safety copy: ${request.safetyCopyVersion}`,
    `Allowed note kinds: ${NOTE_KINDS.join(", ")}`,
    "Prefer skipped decisions when evidence is weak.",
    "Do not infer private facts, protected traits, intent, or mental state.",
    "Return only JSON matching this schema:",
    JSON.stringify(OUTPUT_SCHEMA)
  ].join("\n");
}

function perRequestPrompt(request, priorClassification = null) {
  return JSON.stringify({
    requestId: request.requestId,
    requestedAt: request.requestedAt,
    threshold: request.settingsSnapshot.minimumConfidence,
    post: {
      id: request.post.id,
      author: request.post.author,
      text: request.post.text,
      url: request.post.url,
      detectedAt: request.post.detectedAt
    },
    priorClassification
  });
}

export function buildAnthropicTonalRequest({ request, pass = "first", priorClassification = null }) {
  const model = selectAnthropicTonalModel({
    pass,
    classification: priorClassification,
    threshold: request.settingsSnapshot.minimumConfidence
  });

  return {
    model,
    max_tokens: 1200,
    system: [
      {
        type: "text",
        text: stableRubricPrompt(request),
        cache_control: { type: "ephemeral" }
      }
    ],
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text: perRequestPrompt(request, priorClassification)
          }
        ]
      }
    ]
  };
}

function createGatewaySkippedResponse(request, skippedReason, candidate = null, model = ANTHROPIC_TONAL_MODELS.firstPass) {
  return createSkippedClassifierResponse({
    request,
    skippedReason,
    candidate,
    classifier: {
      provider: "gateway",
      model,
      rubricVersion: request.rubricVersion,
      safetyCopyVersion: request.safetyCopyVersion
    }
  });
}

function extractTextContent(message) {
  return (message?.content ?? [])
    .filter((block) => block?.type === "text")
    .map((block) => block.text)
    .join("\n")
    .trim();
}

function parseAnthropicClassification(message) {
  const text = extractTextContent(message);

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);

    if (!match) {
      return null;
    }

    try {
      return JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
}

async function requestAnthropicClassification({ request, apiKey, fetchImpl, pass, priorClassification }) {
  const payload = buildAnthropicTonalRequest({ request, pass, priorClassification });
  const response = await fetchImpl(ANTHROPIC_MESSAGES_URL, {
    method: "POST",
    headers: {
      "anthropic-version": ANTHROPIC_VERSION,
      "content-type": "application/json",
      "x-api-key": apiKey
    },
    body: JSON.stringify(payload)
  });

  if (!response?.ok) {
    return {
      classification: createGatewaySkippedResponse(request, "gateway_unavailable", null, payload.model),
      payload
    };
  }

  const classification = parseAnthropicClassification(await response.json());
  const validation = validateClassifierResponse(classification);

  if (!validation.ok || classification.requestId !== request.requestId) {
    return {
      classification: createGatewaySkippedResponse(request, "gateway_response_invalid", null, payload.model),
      payload
    };
  }

  return {
    classification,
    payload
  };
}

async function applyFundingRetrieval({ request, classification, exaApiKey, fetchImpl }) {
  if (!request.capabilities?.factual || !request.settingsSnapshot?.factualRetrievalEnabled || !exaApiKey) {
    return classification;
  }

  const retrieval = await searchFundingContextWithExa({
    request,
    apiKey: exaApiKey,
    fetchImpl
  });

  if (classification?.decision?.status === "shown") {
    return attachFundingContextToClassification({
      classification,
      retrieval
    });
  }

  if (retrieval.confidence >= request.settingsSnapshot.minimumConfidence) {
    return createFundingContextResponse({
      request,
      retrieval
    });
  }

  return classification;
}

export async function classifyPostWithAnthropic({ request, apiKey, exaApiKey = "", fetchImpl = fetch }) {
  if (!apiKey) {
    return createGatewaySkippedResponse(request, "gateway_unavailable");
  }

  try {
    const firstPass = await requestAnthropicClassification({
      request,
      apiKey,
      fetchImpl,
      pass: "first",
      priorClassification: null
    });

    if (!isBorderlineTonalDecision(firstPass.classification, request.settingsSnapshot.minimumConfidence)) {
      return applyFundingRetrieval({
        request,
        classification: firstPass.classification,
        exaApiKey,
        fetchImpl
      });
    }

    const borderlinePass = await requestAnthropicClassification({
      request,
      apiKey,
      fetchImpl,
      pass: "borderline",
      priorClassification: firstPass.classification
    });

    return applyFundingRetrieval({
      request,
      classification: borderlinePass.classification,
      exaApiKey,
      fetchImpl
    });
  } catch {
    return createGatewaySkippedResponse(request, "gateway_unavailable");
  }
}
