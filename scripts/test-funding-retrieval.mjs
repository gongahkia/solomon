import {
  createClassifierRequest,
  validateClassifierResponse
} from "../extension/src/shared/classifier-contract.js";
import {
  EXA_SEARCH_URL,
  attachFundingContextToClassification,
  createFundingContextResponse,
  detectFundingAnnouncementClaim,
  searchFundingContextWithExa
} from "../gateway/src/funding-retrieval.js";
import { classifyPostWithAnthropic } from "../gateway/src/anthropic-tonal-classifier.js";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const request = createClassifierRequest({
  source: "retrieval-test",
  settings: {
    tonalClassifierEnabled: true,
    factualRetrievalEnabled: true,
    minimumConfidence: 0.75
  },
  post: {
    id: "urn:li:activity:funding-test",
    author: "Acme AI",
    text: "We raised $12M Series A funding led by Example Ventures to expand our AI workflow platform.",
    url: "https://www.linkedin.com/feed/update/funding-test",
    detectedAt: "2026-06-14T00:00:00.000Z"
  }
});

const claim = detectFundingAnnouncementClaim(request);
assert(claim?.kind === "funding_announcement", "funding claim should be detected");
assert(claim.evidence.some((item) => item.includes("$12M")), "funding amount should be evidence");

const retrieval = await searchFundingContextWithExa({
  request,
  apiKey: "exa-test-key",
  fetchImpl: async (url, options) => {
    assert(url === EXA_SEARCH_URL, "wrong Exa URL");
    assert(options.method === "POST", "Exa method should be POST");
    assert(options.headers["x-api-key"] === "exa-test-key", "missing Exa API key header");
    const body = JSON.parse(options.body);
    assert(body.category === "news", "funding retrieval should use news category");
    assert(body.contents.highlights === true, "funding retrieval should request highlights");

    return {
      ok: true,
      json: async () => ({
        requestId: "exa:req:funding-test",
        results: [
          {
            title: "Acme AI raises $12M Series A",
            url: "https://example.com/acme-series-a",
            publishedDate: "2026-06-01T00:00:00.000Z",
            highlights: ["Acme AI raised a $12 million Series A led by Example Ventures."]
          },
          {
            title: "Example Ventures backs Acme AI",
            url: "https://example.org/example-acme",
            publishedDate: "2026-06-01T00:00:00.000Z",
            summary: "Example Ventures announced its investment in Acme AI."
          }
        ]
      })
    };
  }
});

assert(retrieval.sources.length === 2, "retrieval should keep cited sources");
assert(retrieval.confidence >= request.settingsSnapshot.minimumConfidence, "retrieval should clear threshold");

const factualResponse = createFundingContextResponse({
  request,
  retrieval,
  generatedAt: "2026-06-14T00:00:01.000Z"
});
assert(validateClassifierResponse(factualResponse).ok, "factual response should satisfy contract");
assert(factualResponse.decision.status === "shown", "confident retrieval should render");
assert(factualResponse.note.sources.length === 2, "factual response should include sources");

const tonalClassification = {
  ...factualResponse,
  note: {
    ...factualResponse.note,
    kind: "humblebrag",
    label: "Achievement framing",
    sources: []
  },
  candidate: {
    ...factualResponse.note,
    sources: []
  }
};
const withSources = attachFundingContextToClassification({
  classification: tonalClassification,
  retrieval
});
assert(withSources.note.sources.length === 2, "tonal note should retain factual sources");

const highThresholdRequest = {
  ...request,
  settingsSnapshot: {
    ...request.settingsSnapshot,
    minimumConfidence: 0.95
  }
};
const hiddenResponse = createFundingContextResponse({
  request: highThresholdRequest,
  retrieval,
  generatedAt: "2026-06-14T00:00:01.000Z"
});
assert(hiddenResponse.decision.status === "skipped", "below-threshold retrieval should not render");
assert(!hiddenResponse.note, "below-threshold retrieval should not include visible note");

const skippedTonalResponse = {
  contractVersion: request.contractVersion,
  requestId: request.requestId,
  responseId: "res:anthropic-skipped",
  generatedAt: "2026-06-14T00:00:01.000Z",
  classifier: {
    provider: "gateway",
    model: "claude-haiku-4-5",
    rubricVersion: request.rubricVersion,
    safetyCopyVersion: request.safetyCopyVersion
  },
  note: null,
  candidate: null,
  decision: {
    status: "skipped",
    skippedReason: "no_tonal_signal",
    threshold: request.settingsSnapshot.minimumConfidence
  },
  request
};

let sawExa = false;
const gatewayFundingResponse = await classifyPostWithAnthropic({
  request,
  apiKey: "anthropic-test-key",
  exaApiKey: "exa-test-key",
  fetchImpl: async (url) => {
    if (url === EXA_SEARCH_URL) {
      sawExa = true;
      return {
        ok: true,
        json: async () => ({
          requestId: "exa:req:gateway-funding",
          results: [
            {
              title: "Acme AI raises $12M Series A",
              url: "https://example.com/acme-series-a",
              highlights: ["Acme AI raised a $12 million Series A."]
            },
            {
              title: "Example Ventures backs Acme AI",
              url: "https://example.org/example-acme",
              summary: "Example Ventures led the financing."
            }
          ]
        })
      };
    }

    return {
      ok: true,
      json: async () => ({
        content: [
          {
            type: "text",
            text: JSON.stringify(skippedTonalResponse)
          }
        ]
      })
    };
  }
});

assert(sawExa, "gateway classifier should call Exa for funding claims");
assert(gatewayFundingResponse.decision.status === "shown", "funding retrieval should render after tonal skip");
assert(gatewayFundingResponse.note.kind === "funding_announcement", "gateway funding note kind mismatch");
assert(gatewayFundingResponse.note.sources.length === 2, "gateway funding note should keep sources");

console.log("Funding retrieval tests passed.");
