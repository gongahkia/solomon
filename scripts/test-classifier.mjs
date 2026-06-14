import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { classifyPostTone } from "../extension/src/background/tonal-classifier.js";
import {
  CLASSIFIER_CONTRACT_VERSION,
  createClassifierRequest,
  validateClassifierResponse
} from "../extension/src/shared/classifier-contract.js";

const root = resolve(import.meta.dirname, "..");
const cases = JSON.parse(
  await readFile(resolve(root, "tests", "evals", "tonal-classifier-cases.json"), "utf8")
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

for (const testCase of cases) {
  const request = createClassifierRequest({
    post: testCase.post,
    settings: {
      tonalClassifierEnabled: true,
      minimumConfidence: testCase.expect.minimumConfidence
    },
    source: "eval"
  });
  const response = classifyPostTone(request, {
    generatedAt: "2026-06-14T00:00:00.000Z"
  });
  const validation = validateClassifierResponse(response);

  assert(validation.ok, `${testCase.name}: invalid response ${validation.errors.join(", ")}`);
  assert(
    response.contractVersion === CLASSIFIER_CONTRACT_VERSION,
    `${testCase.name}: wrong contract version`
  );
  assert(
    response.decision.status === testCase.expect.status,
    `${testCase.name}: expected status ${testCase.expect.status}, got ${response.decision.status}`
  );

  if (testCase.expect.status === "shown") {
    assert(response.note, `${testCase.name}: expected a note`);
    assert(
      response.note.kind === testCase.expect.kind,
      `${testCase.name}: expected kind ${testCase.expect.kind}, got ${response.note.kind}`
    );
    assert(response.note.traceId.startsWith("trace:"), `${testCase.name}: missing trace ID`);
    assert(response.request.post.text === testCase.post.text, `${testCase.name}: post text not replayable`);
  } else {
    assert(!response.note, `${testCase.name}: expected no note`);
    assert(
      response.decision.skippedReason === testCase.expect.skippedReason,
      `${testCase.name}: expected skipped reason ${testCase.expect.skippedReason}, got ${response.decision.skippedReason}`
    );
  }
}

console.log(`Classifier evals passed for ${cases.length} cases.`);
