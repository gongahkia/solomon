import {
  createSkippedClassifierResponse,
  validateClassifierRequest,
  validateClassifierResponse
} from "../shared/classifier-contract.js";

export const GATEWAY_CLASSIFIER_CLIENT_VERSION = "decorum-gateway-client-v1";

function gatewayClassifierMetadata(request) {
  return {
    provider: "gateway",
    model: GATEWAY_CLASSIFIER_CLIENT_VERSION,
    rubricVersion: request.rubricVersion,
    safetyCopyVersion: request.safetyCopyVersion
  };
}

function createGatewaySkippedResponse(request, skippedReason, candidate = null) {
  return createSkippedClassifierResponse({
    request,
    skippedReason,
    candidate,
    classifier: gatewayClassifierMetadata(request)
  });
}

function classifyPostUrl(gatewayUrl) {
  const url = new URL(gatewayUrl);

  if (!url.pathname.endsWith("/v1/classify-post")) {
    url.pathname = `${url.pathname.replace(/\/$/, "")}/v1/classify-post`;
  }

  return url;
}

function timeoutSignal(timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  return {
    signal: controller.signal,
    clear: () => clearTimeout(timer)
  };
}

export async function classifyPostWithGateway(
  request,
  { gatewayUrl, accessToken, fetchImpl = fetch, timeoutMs = 8000 } = {}
) {
  const requestValidation = validateClassifierRequest(request);

  if (!requestValidation.ok) {
    return createGatewaySkippedResponse(request, "contract_validation_failed");
  }

  if (!gatewayUrl || !accessToken) {
    return createGatewaySkippedResponse(request, "gateway_unavailable");
  }

  const timeout = timeoutSignal(timeoutMs);

  try {
    const response = await fetchImpl(classifyPostUrl(gatewayUrl), {
      method: "POST",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json"
      },
      body: JSON.stringify(request),
      signal: timeout.signal
    });

    if (!response?.ok) {
      return createGatewaySkippedResponse(request, "gateway_unavailable");
    }

    const classification = await response.json();
    const responseValidation = validateClassifierResponse(classification);

    if (!responseValidation.ok || classification.requestId !== request.requestId) {
      return createGatewaySkippedResponse(request, "gateway_response_invalid");
    }

    if (
      classification.decision.status === "shown" &&
      Number(classification.note?.confidence) < request.settingsSnapshot.minimumConfidence
    ) {
      return createGatewaySkippedResponse(
        request,
        "below_confidence_threshold",
        classification.note
      );
    }

    return classification;
  } catch {
    return createGatewaySkippedResponse(request, "gateway_unavailable");
  } finally {
    timeout.clear();
  }
}
