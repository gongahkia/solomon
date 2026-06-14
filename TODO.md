# Solomon — TODO

Portfolio-mode execution plan. Infra-first, MCP-primary, OSS, SEA jurisdiction first. No business model, no GTM, no sales tasks.

**Demo-target priority** (drives which scenarios get built first): vendor integration (d) → Big Law direct (a) → in-house GC (c) → boutique (b).

**Geo priority**: Singapore first → Malaysia second → UK third → others on demand.

**Conventions**
- `[C]` ships code
- `[D]` ships docs / narrative
- `[R]` research only (no code), output as a doc under `docs/research/` unless stated
- `[X]` repo / infra / CI hygiene
- `[I]` blocked on user input
- Truth labels follow `CLAUDE.md`: `[Inference]`, `[Speculation]`, `[Unverified]`

---

## Workstream 1 — Repositioning & narrative

PRD/README pivot from CLI-first to MCP-first infrastructure with thin curator console. No engine changes here; pure rewrite.

3. [D] Rewrite PRD §6 architecture diagram to show three external consumers (Claude / Copilot / Harvey-like vendor) calling Solomon MCP; relegate curator console to side-channel.
4. [D] Add PRD §6.5 "Curator console scope" — explicit: 3 screens only (Verification Desk, Dependency Review, Audit Pack export). No chat. No retrieval UI.
5. [D] Replace README headline. Draft 3 candidates; pick one. Lead with "MCP-native currency layer for internal legal knowledge — works behind Claude, Copilot, Harvey, iManage."
6. [D] Rewrite README Quick Start: lead with `solomon mcp serve` + Claude Desktop config snippet. Demote raw CLI to "Power users / dev loop" subsection.
7. [D] Re-record headline demo GIF: Claude Desktop calls Solomon via MCP, receives "this position is stale, here's what superseded it, here's the audit pack." Replace existing CLI stale-house-view GIF as headline; keep CLI GIF lower in README.
8. [D] Update README Table of Contents to reflect new ordering: MCP → Curator Console → CLI/SDK → Boundary → Audit → Evaluations.
9. [D] Write `docs/positioning.md`: one-page comparison vs Harvey, iManage Insight+, CoCounsel (TR), Spellbook, Legora, Paxton. Use verified findings from research log.
10. [D] Write `docs/why-currency-not-search.md`: conceptual essay separating Solomon's wedge from "better search over firm DMS."
11. [D] Update CHANGELOG: add v0.2.0 "infrastructure-first pivot" entry referencing PRD rewrite + MCP server.
12. [D] Commit project tagline (≤12 words). Draft three options. Use consistently across README, `pyproject.toml`, GitHub description, MCP directory.
13. [X] Update GitHub repo "About" + topics: `mcp`, `legal-ai`, `knowledge-management`, `bitemporal`, `audit`, `currency-engine`, `singapore`.
14. [X] Update `pyproject.toml` description to match new tagline.
15. [X] Verify CITATION.cff still describes scope accurately post-pivot; update if not.

---

## Workstream 2 — MCP server (primary product surface)

Headline deliverable. Everything else exists to support this.

### 2A — Design

16. [R] Read latest Anthropic MCP spec. Identify required vs optional capabilities (tools, resources, prompts, sampling, roots). Output: `docs/mcp/spec-notes.md`, ≤2 pages.
17. [R] Survey Python MCP SDK landscape: `mcp` (official), FastMCP, anthropic-mcp. Pick one with rationale. [Speculation] official `mcp` SDK is the safer long-term pick.
18. [R] Survey 5+ reference MCP servers in adjacent domains (filesystem, Linear, Notion, Postgres, GitHub). Note auth patterns, error shapes, tool granularity, scoping.
19. [C] Spec MCP tool surface in `docs/mcp/tools.md`. Required tools:
    - `solomon.preflight_context(query, matter_id?, client_id?, max_items?)` — returns current, non-stale firm context safe to inject into a prompt.
    - `solomon.check_currency(knowledge_item_id)` — returns `live | stale_pending | superseded | retired` + reasons + last-verified timestamp.
    - `solomon.get_dependencies(knowledge_item_id, direction=upstream|downstream|both, depth=N)`.
    - `solomon.verify_position(knowledge_item_id, verifier_id, decision, evidence_ref)` — write path for curator console parity.
    - `solomon.ingest(text, source_ref, scope)` — boundary-checked ingest.
    - `solomon.audit_pack(knowledge_item_id, format=json|pdf)` — provenance + dependency + verification history + boundary metadata + hash chain.
    - `solomon.dependency_suggestions(knowledge_item_id)` — proposed edges for human confirmation.
    - `solomon.impact(external_authority_id)` — internal items that depend on this and need re-verification.
20. [C] For each tool, define JSONSchema input/output in `src/solomon/mcp/schemas.py`.
21. [D] Document error taxonomy: `boundary_rejected`, `currency_unknown`, `scope_denied`, `model_routing_failure`, `verification_required`. Land in `docs/mcp/errors.md`.
22. [D] Document tool-call examples (request/response pairs) per tool, `docs/mcp/examples.md`.

### 2B — Implementation

23. [C] Scaffold `src/solomon/mcp/` package: `server.py`, `tools.py`, `schemas.py`, `transport.py`, `auth.py`, `logging.py`.
24. [C] Implement STDIO transport (Claude Desktop / Claude Code default).
25. [C] Implement HTTP/SSE transport for remote-MCP scenarios.
26. [C] Wire each tool from §19 to existing Solomon Python API (`solomon.client`, `solomon.currency`, `solomon.graph`, `solomon.audit`). No duplicated logic.
27. [C] Add `solomon mcp serve` CLI subcommand (STDIO default, `--http` flag for SSE, `--port`, `--host`).
28. [C] Boundary preflight wrapper: every MCP tool that returns firm content runs through `/review` first; reject with structured error if MNPI/PII leaks.
29. [C] Scope enforcement at MCP layer: `matter_id` / `client_id` args restrict the knowledge store query.
30. [C] Auth: bearer-token via env var `SOLOMON_MCP_TOKEN`. No OAuth. No SSO. (Portfolio scope.)
31. [C] Structured logging on every MCP call: tool name, caller, scope, currency outcome, boundary outcome. Land in audit journal.
32. [C] Rate-limit middleware (token-bucket per caller), configurable.
33. [C] Graceful shutdown + connection draining.
34. [C] Health-check tool `solomon.health()` exposing version, store status, journal status, boundary status.

### 2C — Tests

35. [C] Unit tests per MCP tool: happy path, boundary-reject, scope-deny, stale propagation, audit-pack content.
36. [C] Integration test: end-to-end MCP STDIO session simulating Claude Desktop calling `preflight_context`.
37. [C] Property-based tests (Hypothesis): random ingest + supersession sequences → MCP `check_currency` agrees with internal engine.
38. [C] Snapshot tests for tool JSONSchemas (any change requires explicit update).
39. [C] Fuzz test on boundary preflight at MCP boundary (large pasted text, unicode edge cases, base64 blobs).

### 2D — Compatibility & directory listing

40. [R] Anthropic MCP directory: exact submission process, manifest schema, review criteria. Output: `docs/mcp/directory-submission.md`.
41. [C] Build `solomon-mcp.json` manifest fit for the directory (icon, tool list, transport, auth, version).
42. [C] Smoke test in Claude Desktop; record video.
43. [C] Smoke test in Claude Code; record video.
44. [C] Smoke test in Cursor and Continue (best-effort). Note any compatibility gaps. [Speculation] Cursor supports stdio MCP natively.
45. [C] Provide `mcp.json` example config in `examples/mcp/`.
46. [D] `docs/mcp/install.md`: install + register-with-client instructions per client.

---

## Workstream 3 — Curator console (thin web UI, exactly 3 screens)

47. [R] Choose stack. Constraints: thin, single-process deploy, no separate FE build pipeline if avoidable. Candidates: FastAPI + Jinja + HTMX; SvelteKit; Next.js. [Inference] FastAPI + HTMX best fits portfolio simplicity and reuses existing FastAPI app. Decision in `docs/console/stack.md`.
48. [D] Wireframe Verification Desk: inbox of items needing re-verification, evidence preview, "reaffirm / supersede / retire / pin" actions, partner sign-off field.
49. [D] Wireframe Dependency Review: graph view of suggested + confirmed edges, accept/reject per edge, depth control, filter by external authority.
50. [D] Wireframe Audit Pack: pick knowledge item → show provenance, dependency tree, verification history, boundary metadata, hash chain. JSON + PDF export.
51. [C] Implement Verification Desk screen wired to existing Solomon API.
52. [C] Implement Dependency Review screen.
53. [C] Implement Audit Pack screen with JSON + PDF export.
54. [C] Add `solomon console serve` CLI subcommand.
55. [C] Console auth: dev-mode single user + bearer token. Document SSO is out-of-scope (portfolio).
56. [C] Static screenshots → `docs/assets/console/`.
57. [C] Animated GIF per screen → `docs/assets/console/`.
58. [C] Embed screenshots in README and `docs/console/`.
59. [D] `docs/console/user-guide.md`: 1-page walkthrough for a fictional KM lawyer.

---

## Workstream 4 — CLI/SDK polish (secondary infrastructure surface)

60. [C] Audit existing `solomon` CLI verbs; align names with MCP tool names where semantics match. Land migration shims for one release.
61. [C] Add missing CLI commands: `solomon mcp serve`, `solomon console serve`, `solomon impact <authority>`, `solomon audit-pack <id>`, `solomon preflight <query>`.
62. [C] Help text + examples for every command. `--help` should be portfolio-grade.
63. [X] Publish `solomon` to TestPyPI; verify install path.
64. [X] Cut v0.2.0 release on tag; PyPI publish via GH Actions.
65. [C] TypeScript SDK in `packages/solomon-ts/` mirroring MCP tools. Demonstrates vendor integration without Python. Scope: typed client over HTTP/SSE MCP transport.
66. [C] Publish TS SDK to npm under `@solomon/sdk` (scope name TBD).
67. [C] Examples directory restructure: `examples/mcp/`, `examples/console/`, `examples/cli/`, `examples/sdk-ts/`, `examples/scenarios/`.
68. [D] `docs/sdk/python.md` and `docs/sdk/typescript.md`: language-specific quickstarts.

---

## Workstream 5 — Demo scenarios (priority d → a → c → b)

Four end-to-end scenarios in `examples/scenarios/`. Each needs: seed data, runbook, expected outputs, recorded video, screenshots, written walkthrough.

### 5A — Vendor-integration demo (target d, top priority)

69. [D] Pick a fictional vendor name (avoid trademark collision). [I-158] before recording.
70. [C] Python script simulating a vendor agent calling Solomon MCP `preflight_context` before drafting, then injecting only current context into a mock LLM call.
71. [C] Show stale path: when an internal position is stale, the vendor agent receives currency metadata and surfaces "the firm's prior view on X depends on Reg R §12, which moved on date Y" rather than confidently re-using stale text.
72. [D] Record video: side-by-side "without Solomon" (vendor confidently cites stale internal memo) vs "with Solomon" (vendor cites only currently-verified positions, flags stale ones).
73. [D] Write `examples/scenarios/01-vendor-integration/README.md`.
74. [C] Add a "vendor integration smoke test" to CI that runs the scenario headless and asserts the expected outputs.

### 5B — Big Law direct demo (target a)

75. [R] Build a fictional Singapore Big Law firm scenario: 3 practice areas (corporate, banking, employment), 30 internal knowledge items, 8 external authority anchors (Companies Act, Securities & Futures Act, EFMA, MAS Notice 626, IRAS rulings, PDPA 2012 + 2024 amendments).
76. [C] Seed data: YAML in `examples/scenarios/02-biglaw-sg/seed/`.
77. [C] Implement supersession event: MAS Notice 626 amendment → cascade re-verification across 7 dependent internal memos.
78. [D] Walk a "partner" persona through curator console: see flagged items, reaffirm 3, supersede 2, retire 2.
79. [D] Record video; write walkthrough.

### 5C — In-house GC demo (target c)

80. [R] Build a fictional SEA tech company in-house legal scenario: contract templates, employee handbook clauses, internal policy positions.
81. [C] Seed data in `examples/scenarios/03-inhouse-gc/seed/`.
82. [C] Demonstrate PDPA-amendment ripple: clause library has 12 NDAs referencing an old PDPA section; amendment marks them stale-pending.
83. [D] Show MCP integration with a "Copilot-like" tenant assistant consulting Solomon before suggesting NDA language.
84. [D] Record video; write walkthrough.

### 5D — Boutique / mid-market demo (target b, lowest priority)

85. [R] Build a fictional 8-lawyer Singapore boutique: one PSL, ~50 memos, light dependency graph.
86. [C] Seed data in `examples/scenarios/04-boutique-sg/seed/`.
87. [D] Single-binary deploy demo: `docker compose up` → curator console at localhost.
88. [D] Record video; write walkthrough.

---

## Workstream 6 — Jurisdiction work (SEA → UK)

### 6A — Research

89. [R] Singapore PDPA: clauses relevant to law-firm AI use, model-egress, consent. Output: `docs/jurisdictions/sg/pdpa.md`.
90. [R] PDPC Model AI Governance Framework + AI Verify Foundation guidance. Output: `docs/jurisdictions/sg/pdpc-ai.md`.
91. [R] Law Society of Singapore guidance on generative AI use by lawyers (Practice Direction if extant). Output: `docs/jurisdictions/sg/lawsoc.md`.
92. [R] AGC / Singapore Statutes Online / e-Gazette: canonical references for external authorities. Output: `docs/jurisdictions/sg/canonical-sources.md`.
93. [R] LSRA-relevant rules around legal-services regulation, AI-specific where any.
94. [R] MAS FEAT principles (Fairness, Ethics, Accountability, Transparency) — relevant when firms advise on financial services.
95. [R] Malaysia PDPA 2010 + 2024 amendments; relevance to cross-border legal advisory work.
96. [R] UK SRA AI guidance + ICO AI-and-data-protection guidance. Output: `docs/jurisdictions/uk/`.
97. [R] EU AI Act Articles 6 + 52 classification of legal-decision-support systems; relevant to UK firms with EU clients. Output: `docs/jurisdictions/uk/eu-ai-act.md`.
98. [R] Hong Kong PCPD AI Governance Framework (2024) — adjacency to SG/MY for regional positioning.
99. [R] Indonesia PDP Law 2022 — implementation rules as of 2026.

### 6B — Boundary rule updates

100. [C] Audit current boundary PII/MNPI rules; matrix which are SG-correct, MY-correct, UK-correct, EU-correct. Land in `docs/jurisdictions/coverage.md`.
101. [C] SG patterns: NRIC, FIN, UEN, M-class IDs, MyInfo fields, IRAS tax reference numbers.
102. [C] MY patterns: MyKad numbers, business registration numbers (SSM).
103. [C] UK patterns: NI numbers, UTR, Companies House numbers, NHS numbers.
104. [C] Per-jurisdiction test fixtures in `tests/jurisdictions/`.
105. [C] Per-jurisdiction config profile (`--jurisdiction sg|my|uk|eu`) loadable by CLI / MCP / console.
106. [C] Property-based test: each jurisdiction profile is a strict superset of the "minimum" profile (no jurisdiction weakens the boundary).

### 6C — Documentation

107. [D] `docs/jurisdictions/index.md`: matrix showing what Solomon supports per jurisdiction.
108. [D] Per-jurisdiction page explaining boundary rules, citation conventions, known limitations.

---

## Workstream 7 — Evaluations / benchmarks

109. [R] Stanford HAI legal hallucination benchmark methodology. Determine whether Solomon's currency claim can be evaluated against any of its tasks.
110. [R] Damien Charlotin hallucination database: extract subset where failure mode is "real authority later overruled / narrowed / amended." Output: `benchmarks/cases/stale-authority-cases.json`.
111. [C] Synthetic firm-knowledge corpus generator with controllable supersession events: `benchmarks/synthetic/`.
112. [C] Define metrics: stale-detection precision, stale-detection recall, supersession-propagation completeness, false-stale rate, time-to-flag, dependency-completeness.
113. [C] Baseline implementation: semantic-search-only with no temporal logic. Run the same scenarios.
114. [C] Solomon implementation: run the same scenarios with full currency engine.
115. [D] Publish results: `benchmarks/results/2026-Qx.md`, with charts.
116. [C] CI gate: benchmark regression fails build if Solomon's stale-detection precision drops >5% from last release.
117. [C] Property-based tests for bi-temporal invariants (Hypothesis): supersession is acyclic, retire is terminal, valid-time ⊆ ingestion-time, audit-chain hashes verify on rebuild.
118. [C] Reproducibility: every benchmark run produces a manifest (seed, version, env) and is re-runnable from the manifest alone.

---

## Workstream 8 — Documentation / portfolio polish

119. [D] Top-level Mermaid architecture diagram in README: MCP, curator console, CLI, boundary, engine, audit journal.
120. [D] Sequence diagrams in `docs/diagrams/`: (a) MCP preflight, (b) ingestion with boundary review, (c) supersession propagation, (d) verification + audit pack.
121. [D] White-paper `docs/whitepaper.md` — bi-temporal model, dependency propagation, deterministic primitives, boundary, audit chain. ~5,000 words.
122. [D] Positioning page `docs/positioning.md` (cross-ref §9).
123. [D] FAQ `docs/faq.md`: "isn't this just iManage?", "why not Harvey?", "what about retention?", "what about ABA 512 / SRA / PDPA?", "why MCP?", "why not LLM-only RAG?".
124. [D] Prior-art reading list `docs/prior-art.md`: bi-temporal DBs (Datomic, XTDB, Crux, Postgres temporal extensions), Shepard's/KeyCite, citators, ABA 512, EU AI Act, MCP spec.
125. [D] Glossary `docs/glossary.md`: live, stale-pending, superseded, retired, pinned, credence tier, valid-time, ingestion-time, boundary review, audit pack, preflight context.
126. [D] One-pager `docs/one-pager.md`: single-page summary for portfolio reviewers; export as PDF.
127. [D] "5-minute tour" video linked from README.
128. [D] GitHub Pages site under `docs/` deployable via GH Actions: README + diagrams + demo videos + jurisdiction matrix.
129. [D] Duties-map doc `docs/duties-map.md`: each lawyer professional duty (ABA 512, SRA, LawSoc SG) → Solomon feature satisfying it.

---

## Workstream 9 — Engineering hygiene

130. [X] mypy strict on `src/solomon/**`. Fix remaining `Any` leakage.
131. [X] ruff: zero warnings on `src/`, `tests/`, `examples/`.
132. [X] pytest coverage gate ≥90% on `src/solomon/`. Configure in `pyproject.toml`.
133. [X] Hypothesis stateful tests for currency engine state machine.
134. [X] Performance benchmark: dependency propagation at N=1k / 10k / 100k items. Land in `benchmarks/perf/` with regression CI.
135. [X] Verify `docker-compose.server.yml` is the canonical dev deployment; document in README.
136. [X] Verify devcontainer works on clean macOS host and inside GitHub Codespaces.
137. [X] Pre-commit hooks: ruff, mypy, pytest-fast, conventional-commits lint.
138. [X] CI matrix: Python 3.10, 3.11, 3.12. macOS + Ubuntu.
139. [X] Reproducible builds: `uv.lock` committed; CI reinstall hermetic.
140. [X] SBOM generation in CI (`pip-audit` + `cyclonedx-py`).
141. [X] Security scan: `bandit` over `src/`.
142. [X] Verify `flake.nix` builds end-to-end on macOS.
143. [X] License-header check in CI on all source files.

---

## Workstream 10 — Public visibility (portfolio-aligned, not marketing)

144. [X] Tag v0.2.0 release after pivot ships. CHANGELOG entry references PRD/README rewrite + MCP server.
145. [C] Submit `solomon-mcp.json` to Anthropic MCP directory once shipped.
146. [X] Add README badges: PyPI version, MCP-compatible, Python versions, license, CI, coverage, SBOM.
147. [D] Pin GitHub repo on user's profile.
148. [D] Set GitHub repo description + homepage URL (GH Pages site from §128).
149. [D] Add `SECURITY.md` with disclosure contact.
150. [D] Add `SUPPORT.md` clarifying this is a portfolio project; no SLAs.
151. [X] Verify LICENSE is Apache-2.0 and consistent across `pyproject.toml`, `LICENSE`, README badge.

---

## Workstream 11 — Research delegations

All `[R]`. Outputs land in `docs/research/`.

152. [R] R1 — Anthropic MCP directory submission process, manifest schema, review criteria. Sources: claudemcp.com, modelcontextprotocol.io, Anthropic docs.
153. [R] R2 — Singapore PDPA + PDPC AI advisory. Sources: pdpc.gov.sg, lawnet.sg.
154. [R] R3 — MAS FEAT principles + MAS Notice 626/637 if relevant.
155. [R] R4 — LawSoc Singapore + AGC guidance on generative AI by lawyers.
156. [R] R5 — UK SRA AI guidance + ICO AI-and-data-protection.
157. [R] R6 — Harvey Vault public docs: how internal-precedent retrieval is structured.
158. [R] R7 — iManage Insight+ "Knowledge Discovery & Matter Analytics" public API surface.
159. [R] R8 — TR/Anthropic CoCounsel MCP integration shape (May 2026 release).
160. [R] R9 — FastMCP vs official `mcp` SDK current state (Q2 2026).
161. [R] R10 — Bi-temporal DB state-of-art: XTDB v2, Datomic, Crux, Postgres temporal extensions. Confirm Solomon's model is consistent with literature.
162. [R] R11 — Damien Charlotin DB: filter to "real-but-stale authority" failure mode. Build curated subset for demos + benchmarks.
163. [R] R12 — Stanford HAI legal hallucination benchmark: methodology, repo, datasets.
164. [R] R13 — Prior-art check on "internal currency engine for firm knowledge." Conclude with confidence whether the wedge is truly unoccupied or merely unmarketed.
165. [R] R14 — Singapore Statutes Online API + AGC e-Gazette: canonical authority IDs/URIs Solomon can cite.
166. [R] R15 — Legora + iManage May-2026 expanded partnership: public integration surface.
167. [R] R16 — Spellbook (Word add-in): how it injects context; whether MCP-style preflight is plausible there.
168. [R] R17 — Microsoft Copilot connector model for legal: what MCP-style external check looks like inside M365 tenant.
169. [R] R18 — ABA 512 + analogous SG/UK practice guidance: precise duties Solomon helps lawyers satisfy. Output: `docs/duties-map.md`.
170. [R] R19 — Comparable OSS "trust/check layer" projects in adjacent fields (Snyk, Dependabot, in-toto, Sigstore, SLSA, license-compliance tools). Useful prior art for positioning.
171. [R] R20 — Bi-temporal modelling in legal informatics: Snodgrass/Jensen literature; any prior application to legal KM.
172. [R] R21 — How CoCounsel / Westlaw KeyCite represent supersession internally (public sources only).
173. [R] R22 — Anthropic legal program contact / partnership process — research-only, not outreach.

---

## Workstream 12 — Blocked on input

174. [I] Confirm final project tagline from drafted options (§12).
175. [I] Confirm fictional firm + vendor names used in demos do not collide with real SG entities or trademarks (research check before recording).
176. [I] Confirm video hosting: GitHub-attached MP4, YouTube unlisted, or both.
177. [I] Confirm whether `docs/whitepaper.md` should also be posted as a public personal-site essay (user said portfolio-only; defaulting to in-repo only unless overridden).

---

## Workstream 13 — Sequencing notes

Not tasks; guidance for execution order.

- W1 (repositioning) and W11 R1–R3 can start immediately and in parallel.
- W2 (MCP server) is the critical path; W3, W4, W5, W7 all consume it.
- W6 (jurisdictions) can run in parallel with W2 — touches boundary, not MCP.
- W5 (demos) gates on W2 + at least one W3 screen.
- W10 (release) gates on W1 + W2 + W3 + W6A (SG) + W8 minimum viable.
- W7 (evals) gates on W2 + W6B (SG-correct boundary).
