// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import shibahama, { Shibahama, version } from "../index.mjs";

const dir = await mkdtemp(join(tmpdir(), "shibahama-node-"));

try {
  const engine = new Shibahama(join(dir, "store.redb"), 2);

  assert.equal(version(), shibahama.version());
  assert.equal(engine.isOpen(), true);
} finally {
  await rm(dir, { force: true, recursive: true });
}

console.log("node binding lane passed");
