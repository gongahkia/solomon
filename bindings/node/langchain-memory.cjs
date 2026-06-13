// SPDX-License-Identifier: MIT

"use strict";

class LangChainMemory {
  constructor(engine, options = {}) {
    if (!engine) {
      throw new TypeError("LangChainMemory requires a Shibahama engine");
    }
    if (typeof options.embed !== "function") {
      throw new TypeError("LangChainMemory requires an embed(text) function");
    }

    this.engine = engine;
    this.embed = options.embed;
    this.memoryKey = options.memoryKey ?? "history";
    this.inputKey = options.inputKey ?? "input";
    this.outputKey = options.outputKey ?? "output";
    this.topK = options.topK ?? 5;
  }

  get memoryKeys() {
    return [this.memoryKey];
  }

  get memoryVariables() {
    return this.memoryKeys;
  }

  async loadMemoryVariables(inputs) {
    const query = mappingText(inputs, this.inputKey);
    const vector = await this.embed(query);
    const candidates = this.engine.recall(vector, this.topK);
    const history = candidates.map((candidate) => candidate.item.content).join("\n");

    return { [this.memoryKey]: history };
  }

  async saveContext(inputs, outputs) {
    const userText = mappingText(inputs, this.inputKey);
    const assistantText = mappingText(outputs, this.outputKey);
    const content = `Human: ${userText}\nAI: ${assistantText}`;
    const vector = await this.embed(content);

    this.engine.write(content, {
      vector,
      sourceKind: "tool",
      sourceRef: "langchain",
      ingestedBy: "langchain",
    });
  }

  async clear() {
    // Compatibility-only no-op. Shibahama memories are durable; callers should
    // rotate namespaces or stores when they need an empty context.
    return undefined;
  }
}

function mappingText(mapping, preferredKey) {
  if (mapping && Object.prototype.hasOwnProperty.call(mapping, preferredKey)) {
    return String(mapping[preferredKey]);
  }
  if (mapping && typeof mapping === "object") {
    const [first] = Object.values(mapping);

    if (first !== undefined) {
      return String(first);
    }
  }

  return "";
}

module.exports = { LangChainMemory };
