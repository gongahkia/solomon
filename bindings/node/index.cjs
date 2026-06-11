// SPDX-License-Identifier: MIT

"use strict";

const { existsSync, readdirSync } = require("node:fs");
const { join } = require("node:path");

const candidates = [
  join(__dirname, "shibahama.node"),
  join(__dirname, "index.node"),
  ...readdirSync(__dirname)
    .filter((name) => name.endsWith(".node"))
    .map((name) => join(__dirname, name)),
];

const nativePath = candidates.find((candidate) => existsSync(candidate));

if (!nativePath) {
  throw new Error("Unable to find the Shibahama native Node.js binding. Run `npm run build`.");
}

const native = require(nativePath);
const { LangChainMemory } = require("./langchain-memory.cjs");

module.exports = {
  ...native,
  LangChainMemory,
};
