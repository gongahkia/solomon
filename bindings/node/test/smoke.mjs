// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import shibahama, { Shibahama, version } from "../index.mjs";

const require = createRequire(import.meta.url);
const cjs = require("../index.cjs");
const dir = await mkdtemp(join(tmpdir(), "shibahama-node-"));

try {
  const engine = new Shibahama(join(dir, "store.redb"), 2);
  const cjsEngine = new cjs.Shibahama(join(dir, "cjs-store.redb"), 2);

  assert.equal(version(), shibahama.version());
  assert.equal(cjs.version(), version());
  assert.equal(engine.isOpen(), true);
  assert.equal(cjsEngine.isOpen(), true);

  const item = engine.write("Node binding memory", {
    vector: [0, 0],
    sourceKind: "user",
    sourceRef: "smoke",
    validFromUnix: 0,
    ingestedAtUnix: 0,
  });
  const recalled = engine.recall([0, 0], 1, { nowUnix: 0 });
  const streamed = engine.streamRecall([0, 0], 1, { nowUnix: 0 });
  const timeline = engine.timeline([0, 0], 1, 0);
  const timelineStream = engine.streamTimeline([0, 0], 1, 0);
  const why = engine.why(item.id, 0);
  const items = engine.memoryItems();

  assert.equal(item.content, "Node binding memory");
  assert.equal(item.provenance.sourceKind, "user");
  assert.equal(recalled[0].id, item.id);
  assert.equal(streamed.next().id, item.id);
  assert.equal(streamed.next(), null);
  assert.equal(streamed.remaining(), 0);
  assert.equal(timeline[0].id, item.id);
  assert.equal(timelineStream.next().id, item.id);
  assert.equal(engine.reinforce(item.id, "cited"), true);
  assert.equal(why.item.id, item.id);
  assert.ok(items.some((memory) => memory.id === item.id));
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("node binding lane passed");
