// SPDX-License-Identifier: MIT

import { strict as assert } from "node:assert";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Shibahama } from "../../bindings/node/index.mjs";

const dir = await mkdtemp(join(tmpdir(), "shibahama-node-example-"));

try {
  const engine = new Shibahama(join(dir, "store.redb"), 2);
  const item = engine.write("Node examples should stay small and runnable.", {
    vector: [0, 1],
    sourceKind: "user",
    sourceRef: "examples/node/basic-memory.mjs",
    ingestedBy: "node-example",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const recalled = engine.recall([0, 1], 1, { nowUnix: 0 });

  assert.equal(recalled[0].id, item.id);
  assert.equal(engine.reinforce(item.id, "cited"), true);

  const why = engine.why(item.id, 0);
  assert.ok(why);

  console.log(`recalled: ${recalled[0].item.content}`);
  console.log(`credence: ${why.tierCredence}`);
  console.log(`significance: ${why.significance.finalScore.toFixed(3)}`);
} finally {
  await rm(dir, { force: true, recursive: true });
}
