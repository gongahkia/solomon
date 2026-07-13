// SPDX-License-Identifier: MIT

import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Shibahama } from "../../bindings/node/index.mjs";

const fixturePath = process.argv[2];
if (!fixturePath) {
  throw new Error("usage: node scripts/ci/golden-parity-node.mjs scripts/ci/golden-parity.json");
}

const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
if (fixture.schema_version !== 1 || fixture.contract !== "shibahama.memory") {
  throw new Error("unsupported golden parity contract fixture");
}
const dir = await mkdtemp(join(tmpdir(), "shibahama-golden-node-"));

try {
  const engine = new Shibahama(join(dir, "node.redb"), fixture.dimensions, fixture.capacity);
  const ids = new Map();
  const output = { queries: [], timelines: [], signals: [], errors: [], degraded_recalls: [], memories: [], why: [] };

  for (const step of fixture.steps) {
    if (step.op === "write") {
      const item = engine.write(step.content, {
        vector: step.vector,
        sourceKind: step.source_kind,
        sourceRef: step.source_ref,
        ingestedBy: step.ingested_by,
        validFromUnix: step.valid_from_unix,
        ingestedAtUnix: step.ingested_at_unix,
      });
      ids.set(step.source_ref, item.id);
      continue;
    }

    if (step.op === "invalidate") {
      const id = ids.get(step.source_ref);
      if (!id || !engine.invalidate(id, step.valid_to_unix)) {
        throw new Error(`failed to invalidate ${step.source_ref}`);
      }
      continue;
    }

    throw new Error(`unknown step op: ${step.op}`);
  }

  for (const query of fixture.queries) {
    const recalled = engine.recall(query.vector, query.top_k, {
      nowUnix: query.now_unix,
      rawQueryContext: query.raw_query_context,
      includeCold: query.include_cold,
    });
    output.queries.push({
      name: query.name,
      recall: recalled.map(normalizeCandidate),
    });
  }

  for (const query of fixture.timelines) {
    const recalled = engine.timeline(query.vector, query.top_k, query.as_of_unix, {
      rawQueryContext: query.raw_query_context,
      includeCold: query.include_cold,
    });
    output.timelines.push({
      name: query.name,
      recall: recalled.map(normalizeCandidate),
    });
  }

  const memories = engine
    .memoryItems()
    .map(normalizeMemory)
    .sort((left, right) => left.source_ref.localeCompare(right.source_ref));
  output.memories = memories;
  output.why = memories.map((memory) => {
    const trace = engine.why(ids.get(memory.source_ref), fixture.why_now_unix);
    if (!trace) {
      throw new Error(`missing why trace for ${memory.source_ref}`);
    }
    return normalizeWhy(trace);
  });
  for (const signal of fixture.human_signals) {
    const id = ids.get(signal.source_ref);
    if (!id || signal.op !== "affirm") {
      throw new Error(`unsupported human signal: ${signal.name}`);
    }
    output.signals.push({ name: signal.name, applied: engine.affirm(id).applied });
  }
  for (const query of fixture.errors) {
    if (query.op !== "recall") {
      throw new Error(`unknown error operation: ${query.op}`);
    }
    let code;
    try {
      engine.recall(query.vector, query.top_k, { nowUnix: query.now_unix });
    } catch (error) {
      if (
        typeof error.code !== "string" ||
        error.severity !== "fatal" ||
        error.retryable !== false ||
        error.detail !== "vector index operation failed"
      ) {
        throw new Error(`invalid structured error: ${JSON.stringify(error)}`);
      }
      code = error.code;
    }
    if (!code) {
      throw new Error(`${query.name} should fail`);
    }
    if (code !== query.code) {
      throw new Error(`${query.name} returned ${code}`);
    }
    output.errors.push({ name: query.name, code });
  }
  for (const query of fixture.degraded_recalls) {
    const result = engine.recallWithDegradation(query.vector, query.top_k, {
      nowUnix: query.now_unix,
      includeCold: query.include_cold,
    });
    output.degraded_recalls.push({
      name: query.name,
      recall: result.candidates.map(normalizeCandidate),
      unavailable_stages: result.unavailableStages,
    });
  }

  console.log(JSON.stringify(output));
} finally {
  await rm(dir, { force: true, recursive: true });
}

function normalizeCandidate(candidate) {
  return {
    source_ref: candidate.item.provenance.sourceRef,
    tier: candidate.tier,
    credence: candidate.item.credence,
    currency: candidate.currency,
    significance_score: fixed(candidate.significanceScore),
    rank_score: fixed(candidate.rankScore),
  };
}

function normalizeMemory(memory) {
  return {
    source_ref: memory.provenance.sourceRef,
    tier: memory.tier,
    credence: memory.credence,
    significance: fixed(memory.significance),
    valid_to_unix: memory.validToUnix ?? null,
  };
}

function normalizeWhy(trace) {
  return {
    source_ref: trace.item.provenance.sourceRef,
    currency_state: trace.currencyState,
    tier_current: trace.tierCurrent,
    tier_credence: trace.tierCredence,
    final_score: fixed(trace.significance.finalScore),
    valid_to_unix: trace.validToUnix ?? null,
  };
}

function fixed(value) {
  return Number(value).toFixed(6);
}
