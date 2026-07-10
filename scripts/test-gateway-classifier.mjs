import { createClassifierRequest, validateClassifierResponse } from "../extension/src/shared/classifier-contract.js";
import { classifyPostWithGateway } from "../extension/src/background/gateway-classifier.js";
import {
  ANTHROPIC_TONAL_MODELS,
  buildAnthropicTonalRequest,
  classifyPostWithAnthropic,
  selectAnthropicTonalModel
} from "../gateway/src/anthropic-tonal-classifier.js";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const request = createClassifierRequest({
  source: "gateway-test",
  settings: {
    tonalClassifierEnabled: true,
    minimumConfidence: 0.75
  },
  post: {
    id: "urn:li:activity:gateway-test",
    author: "Example Author",
    text: "Comment YES if you want the playbook.",
    url: "https://www.linkedin.com/feed/update/gateway-test",
    detectedAt: "2026-06-14T00:00:00.000Z"
  }
});

const gatewayResponse = {
  contractVersion: request.contractVersion,
  requestId: request.requestId,
  responseId: "res:gateway-test",
  generatedAt: "2026-06-14T00:00:01.000Z",
  classifier: {
    provider: "gateway",
    model: ANTHROPIC_TONAL_MODELS.firstPass,
    rubricVersion: request.rubricVersion,
    safetyCopyVersion: request.safetyCopyVersion
  },
  note: {
    traceId: "trace:gateway-test",
    dedupeKey: "post:gateway-test",
    kind: "engagement_bait",
    label: "Engagement pattern",
    reason: "The post asks for low-friction replies.",
    confidence: 0.88,
    model: ANTHROPIC_TONAL_MODELS.firstPass,
    evidence: ["Comment YES"],
    sources: [],
    generatedAt: "2026-06-14T00:00:01.000Z"
  },
  candidate: null,
  decision: {
    status: "shown",
    skippedReason: null,
    threshold: request.settingsSnapshot.minimumConfidence
  },
  request
};

const successful = await classifyPostWithGateway(request, {
  gatewayUrl: "https://gateway.example.test",
  accessToken: "session-token",
  fetchImpl: async (url, options) => {
    assert(String(url) === "https://gateway.example.test/v1/classify-post", "wrong gateway URL");
    assert(options.method === "POST", "gateway method should be POST");
    assert(options.headers.authorization === "Bearer session-token", "missing bearer token");
    assert(JSON.parse(options.body).requestId === request.requestId, "request body not forwarded");

    return {
      ok: true,
      json: async () => gatewayResponse
    };
  }
});

assert(validateClassifierResponse(successful).ok, "gateway response should satisfy contract");
assert(successful.decision.status === "shown", "gateway success should show valid note");
assert(successful.classifier.provider === "gateway", "gateway response should retain provider");

const unavailable = await classifyPostWithGateway(request, {
  gatewayUrl: "https://gateway.example.test",
  accessToken: "session-token",
  fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({}) })
});

assert(unavailable.decision.status === "skipped", "gateway failure should skip");
assert(unavailable.decision.skippedReason === "gateway_unavailable", "gateway failure reason mismatch");
assert(!unavailable.note, "gateway failure should not render a note");

const invalid = await classifyPostWithGateway(request, {
  gatewayUrl: "https://gateway.example.test",
  accessToken: "session-token",
  fetchImpl: async () => ({ ok: true, json: async () => ({ requestId: "wrong" }) })
});

assert(invalid.decision.status === "skipped", "invalid gateway response should skip");
assert(invalid.decision.skippedReason === "gateway_response_invalid", "invalid response reason mismatch");
assert(!invalid.note, "invalid gateway response should not render a note");

const firstPassPayload = buildAnthropicTonalRequest({ request });
assert(firstPassPayload.model === ANTHROPIC_TONAL_MODELS.firstPass, "first pass should use Haiku");
assert(
  firstPassPayload.system[0].cache_control?.type === "ephemeral",
  "stable rubric prompt should use prompt caching"
);

const borderlineModel = selectAnthropicTonalModel({
  classification: {
    candidate: {
      confidence: 0.72
    }
  },
  threshold: 0.75
});
assert(borderlineModel === ANTHROPIC_TONAL_MODELS.borderline, "borderline pass should use Sonnet");

let anthropicCalls = [];
const anthropicFirstPass = await classifyPostWithAnthropic({
  request,
  apiKey: "anthropic-test-key",
  fetchImpl: async (url, options) => {
    anthropicCalls.push({ url, options });
    const body = JSON.parse(options.body);

    assert(url === "https://api.anthropic.com/v1/messages", "wrong Anthropic URL");
    assert(options.method === "POST", "Anthropic method should be POST");
    assert(options.headers["x-api-key"] === "anthropic-test-key", "missing Anthropic API key header");
    assert(options.headers["anthropic-version"] === "2023-06-01", "missing Anthropic version");
    assert(body.model === ANTHROPIC_TONAL_MODELS.firstPass, "Anthropic first pass should use Haiku");
    assert(body.system[0].cache_control.type === "ephemeral", "Anthropic system prompt should be cached");

    return {
      ok: true,
      json: async () => ({
        content: [
          {
            type: "text",
            text: JSON.stringify(gatewayResponse)
          }
        ]
      })
    };
  }
});

assert(anthropicFirstPass.decision.status === "shown", "Anthropic first pass should return shown response");
assert(anthropicCalls.length === 1, "non-borderline Anthropic request should use one call");

anthropicCalls = [];
const borderlineGatewayResponse = {
  ...gatewayResponse,
  note: {
    ...gatewayResponse.note,
    confidence: 0.74,
    model: ANTHROPIC_TONAL_MODELS.firstPass
  },
  candidate: {
    ...gatewayResponse.note,
    confidence: 0.74,
    model: ANTHROPIC_TONAL_MODELS.firstPass
  }
};

const anthropicBorderline = await classifyPostWithAnthropic({
  request,
  apiKey: "anthropic-test-key",
  fetchImpl: async (url, options) => {
    anthropicCalls.push({ url, options });
    const body = JSON.parse(options.body);
    const text =
      body.model === ANTHROPIC_TONAL_MODELS.borderline
        ? JSON.stringify({
            ...gatewayResponse,
            note: {
              ...gatewayResponse.note,
              model: ANTHROPIC_TONAL_MODELS.borderline
            },
            classifier: {
              ...gatewayResponse.classifier,
              model: ANTHROPIC_TONAL_MODELS.borderline
            }
          })
        : JSON.stringify(borderlineGatewayResponse);

    return {
      ok: true,
      json: async () => ({
        content: [
          {
            type: "text",
            text
          }
        ]
      })
    };
  }
});

assert(anthropicBorderline.classifier.model === ANTHROPIC_TONAL_MODELS.borderline, "borderline Anthropic pass should return Sonnet response");
assert(anthropicCalls.length === 2, "borderline Anthropic request should use two calls");

console.log("Gateway classifier tests passed.");
