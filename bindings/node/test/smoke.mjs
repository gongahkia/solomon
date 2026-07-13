// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import shibahama, { LangChainMemory, Shibahama, capabilities, version } from "../index.mjs";

const require = createRequire(import.meta.url);
const cjs = require("../index.cjs");
const dir = await mkdtemp(join(tmpdir(), "shibahama-node-"));

try {
  const engine = new Shibahama(join(dir, "store.redb"), 2);
  const cjsEngine = new cjs.Shibahama(join(dir, "cjs-store.redb"), 2);

  assert.equal(version(), shibahama.version());
  assert.equal(cjs.version(), version());
  assert.equal(capabilities().schemaVersion, 1);
  assert.ok(capabilities().capabilities.includes("recall"));
  assert.deepEqual(cjs.capabilities(), capabilities());
  assert.equal(engine.isOpen(), true);
  assert.equal(cjsEngine.isOpen(), true);

  try {
    engine.recall([0], 1, { nowUnix: 0 });
    assert.fail("invalid vector should throw");
  } catch (error) {
    assert.equal(error.code, "SHIBA_VECTOR");
    assert.equal(error.severity, "fatal");
    assert.equal(error.retryable, false);
  }

  const item = engine.write("Node binding memory", {
    vector: [0, 0],
    sourceKind: "user",
    sourceRef: "smoke",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  engine.write("Node binding overflow memory", {
    vector: [10, 10],
    sourceKind: "user",
    sourceRef: "smoke-overflow",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const stale = engine.write("Node binding stale memory", {
    vector: [1, 0],
    sourceKind: "file",
    sourceRef: "smoke-stale",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const recalled = engine.recall([0, 0], 1, { nowUnix: 0 });
  const budgeted = engine.recall([0, 0], 2, { nowUnix: 0, maxContextTokens: 3 });
  const streamed = engine.streamRecall([0, 0], 1, { nowUnix: 0 });
  const timeline = engine.timeline([0, 0], 1, 0);
  const timelineStream = engine.streamTimeline([0, 0], 1, 0);
  const why = engine.why(item.id, 0);
  const items = engine.memoryItems();

  assert.equal(item.content, "Node binding memory");
  assert.equal(item.provenance.sourceKind, "user");
  assert.equal(recalled[0].id, item.id);
  assert.deepEqual(
    budgeted.map((candidate) => candidate.id),
    [item.id],
  );
  assert.equal(streamed.next().id, item.id);
  assert.equal(streamed.next(), null);
  assert.equal(streamed.remaining(), 0);
  assert.equal(timeline[0].id, item.id);
  assert.equal(timelineStream.next().id, item.id);
  assert.equal(engine.invalidate(stale.id, 10), true);
  assert.equal(engine.why(stale.id, 10).currencyState, "invalidated");
  assert.equal(engine.reinforce(item.id, "cited"), true);
  assert.equal(
    engine.recall([10, 10], 3, {
      nowUnix: 0,
      similarityWeight: 0,
      significanceWeight: 1,
      recencyWeight: 0,
      graphWeight: 0,
    })[0].id,
    item.id,
  );
  assert.equal(why.item.id, item.id);
  assert.ok(items.some((memory) => memory.id === item.id));
  assert.ok(engine.eventRecords().eventCount >= 2);
  assert.equal(engine.audit(item.id).memoryId, item.id);
  assert.equal(engine.challenge(item.id, "smoke challenge").applied, true);
  assert.equal(engine.affirm(item.id).applied, true);
  assert.equal(engine.pin(item.id).applied, true);
  assert.equal(engine.unpin(item.id).applied, true);
  const corrected = engine.correct(item.id, "Node binding corrected memory");
  assert.equal(corrected.applied, true);
  assert.equal(corrected.replacement.content, "Node binding corrected memory");
  assert.ok(engine.consolidate().appliedCount >= 0);

  const embed = (text) => [Number(text.includes("adapters")), Number(text.includes("async"))];
  const memory = new LangChainMemory(engine, { embed, topK: 3 });
  await memory.saveContext({ input: "remember adapters" }, { output: "stored" });
  const loaded = await memory.loadMemoryVariables({ input: "adapters" });

  assert.deepEqual(memory.memoryKeys, ["history"]);
  assert.deepEqual(memory.memoryVariables, ["history"]);
  assert.ok(loaded.history.includes("Human: remember adapters"));
  await memory.clear();
  const loadedAfterClear = await memory.loadMemoryVariables({ input: "adapters" });
  assert.ok(loadedAfterClear.history.includes("Human: remember adapters"));
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("node binding lane passed");
