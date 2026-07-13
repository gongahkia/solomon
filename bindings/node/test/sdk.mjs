// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { EmbeddedShibahama, createEmbeddedShibahama } from "../sdk.mjs";

const require = createRequire(import.meta.url);
const cjs = require("../sdk.cjs");
const dir = await mkdtemp(join(tmpdir(), "shibahama-sdk-"));
const repositoryScope = { repository: "sdk-repo", visibility: "repository" };
const teamScope = { repository: "sdk-repo", team: "sdk-team", visibility: "team" };

try {
  const sdk = createEmbeddedShibahama({
    path: join(dir, "store.redb"),
    dimensions: 2,
    scope: repositoryScope,
    policy: {
      capture: {
        mode: "automatic",
        actors: { human: false, service: true },
        minimumConfidencePercent: 70,
      },
      recall: { maxCandidates: 1, maxContextTokens: 128 },
    },
  });
  const cjsSdk = new cjs.EmbeddedShibahama({
    path: join(dir, "cjs.redb"),
    dimensions: 2,
    scope: repositoryScope,
  });

  assert.ok(sdk instanceof EmbeddedShibahama);
  assert.equal(cjsSdk.engine.isOpen(), true);
  assert.equal(sdk.simulateRecallPolicy(10).decision.effective_candidates, 1);
  assert.equal(
    sdk.simulateCapturePolicy("user", { actor: "human", intent: "manual" }).decision.outcome,
    "deny",
  );
  assert.throws(
    () => sdk.write("denied", { vector: [1, 0] }),
    (error) => error.code === "SHIBA_POLICY",
  );

  const item = sdk.write("embedded SDK memory", {
    vector: [1, 0],
    sourceKind: "user",
    sourceRef: "sdk-repo",
    actor: "service",
    intent: "automatic",
    confidencePercent: 80,
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const recalled = sdk.recall([1, 0], 10, { nowUnix: 0 });

  assert.equal(item.scope.repository, repositoryScope.repository);
  assert.equal(recalled.length, 1);
  assert.equal(recalled[0].id, item.id);
  assert.equal(sdk.why(item.id, 0).item.id, item.id);
  assert.equal(sdk.reinforce(item.id), true);
  assert.ok(sdk.eventRecords().eventCount >= 3);
  assert.equal(sdk.memoryItems().length, 1);
  assert.throws(
    () => sdk.write("scope override", { scope: teamScope }),
    /operation scope conflicts/,
  );

  const teamSdk = sdk.withScope(teamScope);
  const teamItem = teamSdk.write("team SDK memory", {
    vector: [0, 1],
    sourceKind: "user",
    actor: "service",
    intent: "automatic",
    confidencePercent: 80,
  });
  assert.equal(teamSdk.memoryItems().length, 1);
  assert.equal(teamSdk.recall([0, 1], 1)[0].id, teamItem.id);
  assert.equal(sdk.memoryItems().length, 1);
  assert.throws(() => sdk.invalidate(teamItem.id, 10), (error) => error.code === "SHIBA_INVALID_REQUEST");
  assert.equal(teamSdk.invalidate(teamItem.id, 10), true);
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("embedded SDK lane passed");
