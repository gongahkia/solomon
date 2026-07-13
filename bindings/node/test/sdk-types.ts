import { EmbeddedShibahama, createEmbeddedShibahama } from "shibahama/sdk";

const scope = { repository: "types-repo", visibility: "repository" } as const;
const sdk = createEmbeddedShibahama({
  path: "types.redb",
  dimensions: 2,
  scope,
  policy: {
    capture: { mode: "automatic", actors: { service: true } },
    recall: { maxCandidates: 4, scopes: { repository: true } },
  },
});

const item = sdk.write("typed memory", {
  vector: [1, 0],
  sourceKind: "user",
  actor: "service",
  intent: "automatic",
  confidencePercent: 90,
});
const candidates = sdk.recall([1, 0], 1, { includeCold: false });
const scoped: EmbeddedShibahama = sdk.withScope(scope);

item.id;
candidates[0]?.rankScore;
scoped.simulateRecallPolicy(1).decision;

// @ts-expect-error embedded scope is immutable per SDK facade
sdk.write("wrong scope", { scope });
