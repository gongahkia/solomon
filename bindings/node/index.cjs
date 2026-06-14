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

const parsedMethods = {
  eventRecords: "eventRecordsJson",
  audit: "auditJson",
  consolidate: "consolidateJson",
  challenge: "challengeJson",
  affirm: "affirmJson",
  correct: "correctJson",
  pin: "pinJson",
  unpin: "unpinJson",
};

for (const [method, jsonMethod] of Object.entries(parsedMethods)) {
  if (
    native.Shibahama &&
    native.Shibahama.prototype &&
    typeof native.Shibahama.prototype[jsonMethod] === "function" &&
    typeof native.Shibahama.prototype[method] !== "function"
  ) {
    native.Shibahama.prototype[method] = function parsedJsonMethod(...args) {
      return JSON.parse(this[jsonMethod](...args));
    };
  }
}

module.exports = {
  ...native,
  LangChainMemory,
};
