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

function annotateError(error) {
  if (!(error instanceof Error) || String(error.code ?? "").startsWith("SHIBA_")) {
    return error;
  }

  const match = /\[(SHIBA_[A-Z_]+)\]/.exec(error.message);
  error.code = match ? match[1] : "SHIBA_INTERNAL";
  error.severity = ["SHIBA_RECALL", "SHIBA_TASK"].includes(error.code)
    ? "recoverable"
    : "fatal";
  error.retryable = error.severity === "recoverable";
  return error;
}

if (typeof native.capabilitiesJson === "function") {
  native.capabilities = () => {
    const document = JSON.parse(native.capabilitiesJson());

    return {
      schemaVersion: document.schema_version,
      version: document.version,
      memorySchemaVersion: document.memory_schema_version,
      capabilities: document.capabilities,
    };
  };
}

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

if (native.Shibahama?.prototype) {
  for (const name of Object.getOwnPropertyNames(native.Shibahama.prototype)) {
    if (name === "constructor" || typeof native.Shibahama.prototype[name] !== "function") {
      continue;
    }
    const method = native.Shibahama.prototype[name];
    native.Shibahama.prototype[name] = function structuredNativeError(...args) {
      try {
        return method.apply(this, args);
      } catch (error) {
        throw annotateError(error);
      }
    };
  }
}

module.exports = {
  ...native,
  LangChainMemory,
};
