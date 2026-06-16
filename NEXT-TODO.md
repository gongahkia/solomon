# Solomon — TODO additions (post-audit, June 2026)

> Drop-in continuation of `TODO.md`. Same conventions: `[C]` code, `[D]` docs, `[R]` research, `[X]` infra/CI, `[I]` blocked on input. Truth labels per `CLAUDE.md`. Numbering continues from 177.
>
> These workstreams encode an architecture + product audit. The core temporal engine is sound (currency state machine, event-sourced store, BFS propagation, hash-chained audit — all real, 89% coverage, honest skips). The audit's three findings drive everything below: (1) god-object files hurt the senior-engineer read; (2) breadth is bought at the cost of finished surfaces, which hurts the product-mindset read; (3) the three most interesting/defensible subsystems (contradiction, verification workflow, local-model path) are the thinnest. Crack 1 (Kaypoh composition) is RESOLVED — Kaypoh is in-repo under a different module name; no task needed.

---

## Workstream 14 — Architecture refactor (god-object decomposition)

The single most visible quality tell in the repo. A reviewer skims file sizes before reading logic; three files over ~800 lines read as "grew without being shaped." The method seams already exist — this is mechanical, low-risk, high-signal. Refactor behind the existing test suite; **no behavior change**, coverage must not drop.

178. [X] Snapshot baseline before touching anything: record current `pytest --cov` output and per-file line counts into `docs/refactor/baseline-2026-06.md`. Every task below must preserve green tests + ≥89% coverage.
179. [C] Decompose `src/solomon/api/service.py` (1,130 lines). It currently fuses ingestion, recall, answer, authority-change, and load-bearing enforcement in one `SolomonService`. Split along the existing method seams into a thin façade (`service.py`, orchestration only) delegating to: `services/ingestion.py`, `services/recall.py`, `services/answer.py`, `services/authority.py`. Keep the public `SolomonService` interface identical so API/MCP/CLI callers are untouched.
180. [C] Decompose `src/solomon/store/postgres.py` (979 lines). Separate connection/pool management, DDL/migration, the knowledge-item store, and the event store into distinct modules under `store/postgres/`. Mirror the SQLite store's module boundaries so the two backends stay structurally parallel (this parallelism is itself a reviewer signal).
181. [C] Decompose `src/solomon/mcp/tools.py` (795 lines). Split the `SolomonMCPRuntime`, tool registration, and per-tool handlers into `mcp/tools/` with one module per tool group. Keep `register_solomon_tools` as the single public entrypoint.
182. [X] Add a CI guardrail: fail the build if any file under `src/solomon/` exceeds 500 lines (configurable allowlist for any deliberate exception, with a comment justifying it). This prevents regression and signals intentionality.
183. [D] Write a short ADR `docs/adr/0001-service-decomposition.md`: why the façade-over-domain-modules shape, what the seams are, and the 500-line rule rationale. One ADR here does more for the senior-engineer read than three new features.
184. [C] After decomposition, re-run mypy strict (§130) over the new module layout; fix any `Any` leakage exposed by the smaller surfaces.

---

## Workstream 15 — Finish-vs-cut decisions (surface discipline)

Breadth is the audit's main product-mindset liability: a TS SDK with only a typecheck, a PyInstaller spec that never compiled, and named-vendor "integrations" that are docs-only all read as "prioritized surface area over the thing customers pay for." The product-mindset move is to cut to the spine and finish it to a shine. Each item below is an explicit FINISH or CUT/DEMOTE decision — no half-built surface survives unlabeled.

### 15A — Decisions blocked on user (resolve these first; they gate the rest)

185. [I] **TS SDK** — decide: (a) FINISH = add real runtime/unit tests against a mock transport, publish to npm, keep as a first-class surface; or (b) CUT = remove from headline surfaces, move `packages/solomon-ts/` to an `experimental/` path with a README stating "typecheck-only, not production." Audit recommendation: CUT unless a concrete consumer exists, because an untested published SDK is a liability under scrutiny.
186. [I] **PyInstaller / local-binary packaging** — decide: FINISH = actually build the binary in CI and smoke-test the offline SKU end-to-end; or DEMOTE = mark `packaging/` as roadmap in README and remove the "offline binary" claim from headline copy until built. Audit recommendation: DEMOTE; the Docker path is the real local-deploy story for now.
187. [I] **Curator console** — decide its tier: first-class surface (then 15C applies) or explicitly-secondary (then keep the 3 ASGI-tested screens but stop claiming it as a primary surface). Audit recommendation: keep as secondary; MCP is the primary surface.
188. [I] **Named-vendor integration language** (Harvey / iManage / Copilot) — confirm these get reworded everywhere from "integration" to "MCP-compatible; works with any MCP host." The generic MCP surface is the real, honest integration story; named vendors are positioning, not code.

### 15B — Once decisions land, execute the CUTs

189. [D] Rewrite README + PRD + `pyproject.toml` + GitHub "About" to claim ONLY the finished spine as primary surfaces: MCP, FastAPI, CLI, audit pack. Everything else appears under an explicit "Roadmap / experimental" heading. A reviewer respects a deliberately scoped surface far more than four half-built ones.
190. [C] For each CUT surface: move code to `experimental/` (or delete), strip its tests from the headline suite (keep them runnable separately), and remove its claims from all docs. Update §63–66 (CLI/SDK polish) and §87 (single-binary demo) to match the decisions from 185–186.
191. [X] Audit all docs (`rg` for vendor names + "SDK" + "binary" + "offline") for any remaining claim that outruns the code. The grep-the-repo-against-the-PRD test is exactly what a sharp interviewer runs; pass it preemptively.

### 15C — If FINISH was chosen for any surface, finish it properly

192. [C] (conditional on 185=FINISH) TS SDK: real unit tests covering each client method against a mock transport, error-path coverage, a published example, and a CI job that runs `npm test` — not just typecheck.
193. [C] (conditional on 186=FINISH) Build the PyInstaller binary in CI on macOS + Linux, run the offline SKU headless against the stale-house-view scenario, assert identical outputs to the server SKU.

---

## Workstream 16 — Drill: contradiction reasoning (thinnest core claim, highest differentiation)

Supersession is real; contradiction is currently a metadata/content heuristic in `src/solomon/currency/supersession.py`. This is the highest-value drill because it is the part incumbents can't cheaply copy (it's not "freshness as a tag") and it's the most intellectually interesting piece for an interview. Aim for a modest but real capability, not a research project.

194. [R] Define the contradiction taxonomy Solomon will actually detect, output to `docs/research/contradiction-taxonomy.md`. At minimum: (a) two LIVE positions citing the same external authority but reaching opposite conclusions; (b) a LIVE position whose conclusion is negated by a newer LIVE position in the same matter/scope; (c) a position contradicting a confirmed supersession. Explicitly scope OUT full semantic legal reasoning — name what is deliberately not attempted and why.
195. [C] Implement detector (a): same-authority-opposite-conclusion. Use the existing dependency graph to find positions sharing an external-authority target, then flag conclusion divergence. Start deterministic (structured conclusion field / polarity tag captured at ingest); document where an LLM-assisted classifier could later improve recall.
196. [C] Surface contradictions as a first-class signal at recall and in the audit pack — not just a metadata field. A contradiction between two live positions is a partner-grade finding ("the firm holds two opposing live views on X"); it should be loud.
197. [C] Add a `currency_state` interaction rule + tests: a contradiction does NOT auto-supersede (humans decide), but it MUST flag both items for verification and record the contradiction in the audit chain.
198. [C] Property test: contradiction detection is symmetric (if A contradicts B, B contradicts A) and never fires between an item and its own successor.
199. [D] Add a contradiction scenario to `examples/scenarios/` mirroring the stale-house-view format: two live memos, same authority, opposite advice; Solomon flags it, a warehouse baseline does not.

---

## Workstream 17 — Drill: verification workflow (converts a feature into the moat)

Verification is currently a timestamp + endpoints, no human loop. The PRD's whole defensibility pitch is "provable record of what the firm knew, when, on what basis, and what verification occurred." A real reviewer-assignment → re-verify → re-attest loop, surfaced in the audit pack, is what turns a feature into a moat that survives a challenge.

200. [C] Model the verification lifecycle as explicit states/events (not just `last_verified_at`): `verification_requested → assigned → in_review → reaffirmed | superseded | retired`, each an append-only event in the existing event store. Reuse the bitemporal event pattern; do not invent a parallel store.
201. [C] Reviewer assignment: a stale-flagged item can be assigned to a named reviewer (role/identity from existing auth/tenancy). Assignment, reassignment, and completion are audit-chained events.
202. [C] Re-attestation: completing a review records who, when, on what basis (free-text rationale + optional source pointer), and transitions currency state. Reaffirmation resets the verification clock; supersession/retire follow existing paths.
203. [C] Surface the verification queue through MCP (a tool to list "items needing verification, optionally by reviewer/scope") and through the curator console verification screen. MCP-first per the existing positioning.
204. [C] Extend the audit pack to render the full verification history per item: every assignment and attestation, in order, with hashes that verify on rebuild. This is the artifact that survives a challenge — make it the centerpiece of the audit pack, not an addendum.
205. [C] Tests: full loop (flag → assign → reaffirm) end-to-end; audit chain replays and verifies; reviewer identity is captured; an item cannot be marked verified without a recorded basis.
206. [X] Make verification policy days **configurable and auditable** (resolves the audit's "hardcoded `VerificationPolicy`" weakness): load from settings/config, record the active policy version in the audit chain so a reader knows which thresholds applied at decision time. Same treatment for `CredencePolicy` thresholds (§4 credence weakness).

---

## Workstream 18 — Drill: prove the local-model / ZDR path end-to-end (once)

Model routing is real code (`RemoteZDREndpoint`, `OpenAIResponsesEndpoint`, `LocalModelEndpoint`) but never touches a live endpoint in tests — everything is `httpx.MockTransport` / `CapturingEndpoint`. The offline-default + ZDR claim is the strongest privilege story Solomon has; it must not rest entirely on mocks. One real integration test converts "Partial" to "real."

207. [C] Add an opt-in live integration test (gated like the existing live-Postgres skip: runs only when `SOLOMON_TEST_LOCAL_MODEL_URL` is set) that starts/points at a local model server (Ollama default `http://127.0.0.1:11434`), runs a real `/answer` through the full recall → boundary → router → model path, and asserts a non-empty grounded response with the boundary applied (client identity absent, `[CLIENT_1]` token present in the model-visible prompt).
208. [X] Add a CI job (or a documented `make demo-local`) that spins up a tiny local model in a container and runs §207 headless, so the offline path has at least one machine-verified green run per release. If CI can't host a model, document the manual run and record one verified output into `docs/verification/local-model-run.md`.
209. [C] Add the equivalent opt-in live test for the remote ZDR path against an OpenAI-compatible endpoint (gated on an env var + key), asserting zero-egress mode correctly *blocks* it and that explicit enablement is required. The negative test (egress disabled → refused) matters more than the positive for the privilege story.
210. [D] Document the offline-default guarantee precisely in `docs/zero-egress.md`: what "ZDR" means here, what is sent vs withheld, the exact code path that enforces zero egress by default, and the boundary token round-trip. Cite the enforcing functions by name.

---

## Workstream 19 — Add: partner-facing currency report (the YC translation)

ONLY after the spine is finished (W14–W18). This is the single feature that reframes Solomon from a dev tool into something a managing partner sees value in — the product-mindset artifact. It uses only capabilities that already exist plus the W17 verification data.

211. [C] Implement a "currency report" generator: given a scope (firm / practice area / matter) and a period, produce the set of positions that went stale, were superseded, retired, or flagged contradictory in that window, each with the authority that moved, the date, the dependent items, and current verification status. Pure read over existing event store + graph; no new storage.
212. [C] Expose it three ways consistent with surface priority: MCP tool (primary), API endpoint, and a curator-console screen that renders it. Reuse, do not re-derive, the recall/currency/graph logic.
213. [C] Export the report as the existing audit-pack format AND a human-readable rendering (the console PDF is currently minimal per the audit — this is the reason to make that PDF good, scoped to this one report rather than polishing PDF everywhere).
214. [D] Reframe the headline demo around this report for the product audience: "here are the 14 firm positions that went stale this quarter and why" is the partner-legible version of the stale-house-view scenario. Add as a variant walkthrough; keep the technical scenario for the engineer audience.
215. [D] One-paragraph addition to `docs/positioning.md`: the currency report is the visible output that distinguishes "currency engine" from "search with a freshness tag" to a non-technical buyer.

---

## Sequencing notes (append to Workstream 13)

- **W14 (refactor) first and alone** — it's behavior-preserving and de-risks everything after it by shrinking the files later tasks touch. Do not interleave feature work into the refactor PRs.
- **W15A (the `[I]` decisions) next** — they gate W15B/C and several existing tasks (§63–66, §87). Resolve before writing more surface code.
- **W16 / W17 / W18 are independent** and can run in parallel after W14. If forced to rank for interview impact: W17 (verification moat) > W16 (contradiction differentiation) > W18 (one live-model test). For privilege-story credibility specifically, W18 jumps to first.
- **W19 gates on W17** (needs verification-status data) and on the spine being finished. It is the last thing built, not the first.
- W14's 500-line CI gate (§182) should land before W16/W17/W19 add code, so new modules are born compliant.
