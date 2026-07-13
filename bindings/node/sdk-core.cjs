// SPDX-License-Identifier: MIT

"use strict";

function createEmbeddedSdk(native) {
  class EmbeddedShibahama {
    constructor(options) {
      if (!options || typeof options !== "object") throw new TypeError("embedded SDK options are required");
      if (typeof options.path !== "string" || options.path.length === 0) throw new TypeError("path is required");
      if (!Number.isInteger(options.dimensions) || options.dimensions <= 0) {
        throw new TypeError("dimensions must be a positive integer");
      }
      if (options.capacity !== undefined && (!Number.isInteger(options.capacity) || options.capacity <= 0)) {
        throw new TypeError("capacity must be a positive integer");
      }
      this.engine = new native.Shibahama(options.path, options.dimensions, options.capacity);
      this.scope = normalizeScope(options.scope);
      this.policy = normalizePolicy(options.policy);
      this.engine.configurePolicy(toNativePolicy(this.policy));
    }

    static open(options) {
      return new EmbeddedShibahama(options);
    }

    static #bound(engine, scope, policy) {
      const sdk = Object.create(EmbeddedShibahama.prototype);
      sdk.engine = engine;
      sdk.scope = scope;
      sdk.policy = policy;
      return sdk;
    }

    withScope(scope) {
      return EmbeddedShibahama.#bound(this.engine, normalizeScope(scope), this.policy);
    }

    simulateCapturePolicy(sourceKind, options = {}) {
      const bound = bindScope(options, this.scope);
      return parsePolicy(this.engine.simulateCapturePolicy(sourceKind, bound));
    }

    simulateRecallPolicy(topK, options = {}) {
      const bound = bindScope(options, this.scope);
      return parsePolicy(this.engine.simulateRecallPolicy(topK, bound, this.scope));
    }

    write(content, options = {}) {
      return this.engine.write(content, bindScope(options, this.scope));
    }

    recall(queryVector, topK, options = {}) {
      return this.engine.recall(queryVector, topK, bindScope(options, this.scope));
    }

    recallWithDegradation(queryVector, topK, options = {}) {
      return this.engine.recallWithDegradation(queryVector, topK, bindScope(options, this.scope));
    }

    timeline(queryVector, topK, asOfUnix, options = {}) {
      return this.engine.timeline(queryVector, topK, asOfUnix, bindScope(options, this.scope));
    }

    invalidate(memoryId, validToUnix) {
      return this.engine.invalidateScoped(memoryId, validToUnix, this.scope);
    }

    reinforce(memoryId, outcome = "cited") {
      return this.engine.reinforceScoped(memoryId, outcome, this.scope);
    }

    why(memoryId, nowUnix) {
      return this.engine.whyScoped(memoryId, nowUnix, this.scope);
    }

    memoryItems() {
      return this.engine.memoryItemsScoped(this.scope);
    }

    eventRecords() {
      return JSON.parse(this.engine.eventRecordsScopedJson(this.scope));
    }
  }

  return {
    EmbeddedShibahama,
    createEmbeddedShibahama: EmbeddedShibahama.open,
  };
}

function normalizeScope(scope) {
  if (!scope || typeof scope !== "object") throw new TypeError("scope is required");
  if (typeof scope.repository !== "string" || scope.repository.length === 0) {
    throw new TypeError("scope.repository is required");
  }
  if (scope.visibility !== "repository" && scope.visibility !== "team") {
    throw new TypeError("scope.visibility must be repository or team");
  }
  const team = scope.team ?? undefined;
  if (scope.visibility === "repository" && team !== undefined) {
    throw new TypeError("repository scope must not specify team");
  }
  if (scope.visibility === "team" && (typeof team !== "string" || team.length === 0)) {
    throw new TypeError("team scope requires team");
  }
  return Object.freeze({ repository: scope.repository, visibility: scope.visibility, ...(team ? { team } : {}) });
}

function bindScope(options, scope) {
  if (!options || typeof options !== "object") throw new TypeError("options must be an object");
  if (options.scope !== undefined && !sameScope(normalizeScope(options.scope), scope)) {
    throw new TypeError("operation scope conflicts with the embedded SDK scope");
  }
  const { scope: ignored, ...bound } = options;
  return { ...bound, scope };
}

function sameScope(left, right) {
  return left.repository === right.repository && left.visibility === right.visibility && left.team === right.team;
}

function normalizePolicy(policy = {}) {
  if (!policy || typeof policy !== "object") throw new TypeError("policy must be an object");
  const capture = policy.capture ?? {};
  const recall = policy.recall ?? {};
  if (typeof capture !== "object" || typeof recall !== "object") {
    throw new TypeError("policy.capture and policy.recall must be objects");
  }
  return Object.freeze({
    capture: Object.freeze({ ...capture }),
    recall: Object.freeze({ ...recall }),
  });
}

function toNativePolicy(policy) {
  const capture = policy.capture;
  const recall = policy.recall;
  const actors = capture.actors ?? {};
  const sources = capture.sources ?? {};
  const captureScopes = capture.scopes ?? {};
  const recallScopes = recall.scopes ?? {};
  return {
    captureMode: capture.mode,
    captureAllowHuman: actors.human,
    captureAllowAgent: actors.agent,
    captureAllowAutomation: actors.automation,
    captureAllowService: actors.service,
    captureAllowUser: sources.user,
    captureAllowFile: sources.file,
    captureAllowWeb: sources.web,
    captureAllowTool: sources.tool,
    captureAllowRepository: captureScopes.repository,
    captureAllowTeam: captureScopes.team,
    captureMinimumConfidencePercent: capture.minimumConfidencePercent,
    recallMaxCandidates: recall.maxCandidates,
    recallMaxContextTokens: recall.maxContextTokens,
    recallAllowCold: recall.allowCold,
    recallAllowInstructions: recall.allowInstructions,
    recallAllowRepository: recallScopes.repository,
    recallAllowTeam: recallScopes.team,
  };
}

function parsePolicy(value) {
  return JSON.parse(value);
}

module.exports = { createEmbeddedSdk };
