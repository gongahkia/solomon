import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  CLASSIFIER_CONTRACT_VERSION,
  validateClassifierRequest,
  validateClassifierResponse
} from "../extension/src/shared/classifier-contract.js";

const root = resolve(import.meta.dirname, "..");
const request = JSON.parse(
  await readFile(resolve(root, "tests", "contracts", "classifier-request.json"), "utf8")
);
const response = JSON.parse(
  await readFile(resolve(root, "tests", "contracts", "classifier-response.json"), "utf8")
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const requestValidation = validateClassifierRequest(request);
const responseValidation = validateClassifierResponse(response);

assert(requestValidation.ok, `request contract invalid: ${requestValidation.errors.join(", ")}`);
assert(responseValidation.ok, `response contract invalid: ${responseValidation.errors.join(", ")}`);
assert(
  request.contractVersion === CLASSIFIER_CONTRACT_VERSION,
  "request uses the wrong contract version"
);
assert(response.requestId === request.requestId, "response must preserve requestId");
assert(response.request.post.text === request.post.text, "response must include replayable input");

console.log("Gateway contract examples passed.");
