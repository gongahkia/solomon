# Security

Shibahama treats memory as a security boundary, not just a retrieval feature.
The current implementation has concrete guardrails for poisoning resistance,
provenance, namespace filtering, and metadata-only server logging. It is still a
pre-release system, and several controls are extension points rather than
complete production guarantees.

## Threat Model

The primary risks are:

- stale or contradicted memories being returned as current;
- low-credence or attacker-controlled memories outranking authoritative facts;
- stored memory text acting as prompt-injection content when read back;
- reconstruction turning recall into an automatic write primitive;
- server logs leaking memory contents, query text, or embeddings;
- users assuming the default embedded store encrypts content at rest.

The current design focuses on making these risks explicit and inspectable.

## Provenance And Credence

Every memory write requires provenance. `SourceKind` drives conservative default
credence:

- `User` starts as `FirmAuthoritative`;
- `File` starts as `VerifiedSource`;
- `Agent` and `Tool` start as `ModelInferred`;
- `Web` starts as `Unverified`.

This mapping is configurable through `ShibahamaConfig::ingest_credence`, which
uses `IngestCredencePolicy` to map source kinds to default credence tiers.
Per-write explicit credence still overrides the configured default.

Recall candidates include provenance and credence. Ranking sorts by credence
before score, so a low-credence memory cannot outrank a higher-credence memory
solely because it is semantically closer or recently reinforced.

Suspicious provenance inspection currently flags:

- file, tool, or web memories without a stable source reference;
- web source refs that are not HTTP(S) URLs;
- non-user sources claiming `FirmAuthoritative` credence.

Provenance can also carry an optional keyed attribution signature. The core
model exposes `ProvenanceSigningKey`, `Provenance::with_signature`, and
`Provenance::verify_signature`, using BLAKE3 keyed hashing over source kind,
source ref, and ingester. This protects attribution fields when the signing key
is kept secret. It is not a content-integrity signature and it is not a public
key infrastructure.

## Poisoning Resistance

Shibahama separates trust from usefulness. Significance is based on use, but
credence remains the trust gate. This prevents repeated retrieval from
automatically laundering weak provenance into authority.

Model-generated and web-sourced content default to weaker trust and colder
accessibility. Reconstructed proposals also enter at low credence and cold tier
until corroborated.

Instruction memories are represented with `MemoryKind::Instruction`. Default
recall returns facts only; callers must explicitly opt in to instruction recall.

## Read Safety

Stored memory text is sanitized at the recall boundary before it is returned to
callers. The current read-safety filter:

- removes non-whitespace control characters;
- prefixes lines that look like LLM role directives such as `system:`,
  `developer:`, `assistant:`, `tool:`, or `user:`;
- reports read-safety findings on recall candidates.

This is a defensive filter, not a full prompt-injection solution. Host agents
should still treat recalled memory as untrusted data, preserve provenance, and
avoid executing stored instructions unless they intentionally requested
instruction memories.

`core/src/read_safety.rs` also exposes a `SanitizingGateway` trait. Sync recall
requests can provide a custom gateway when a deployment needs a tokenization or
redaction boundary before memory text leaves the store. The repository only
ships the default gateway; it does not implement domain-specific tokenization.

## Reconstruction Gate

Reconstruction is explicitly gated. A normal read or recall may flag a
load-bearing, possibly stale memory, but it does not revalidate or mutate memory
state automatically.

Reconstruction work requires explicit re-validation mode or an opt-in idle
planning pass through `BackgroundReconstructionConfig::validate_on_idle`. The
idle path only plans budgeted re-validation actions; it does not write proposed
updates or invalidate memories on its own.

Proposed updates enter quarantine at lower credence and cold tier. Promotion
requires one of:

- human confirmation;
- a high-credence source;
- enough independent consistent observations.

Accepted replacements invalidate superseded memories by closing `valid_to`; they
do not overwrite or delete historical state.

## Bi-Temporal Currency

Default recall filters to memories believed at the query time. Invalidated facts
remain in durable history but are excluded from normal current recall.

Timeline queries can inspect what Shibahama believed at a previous instant.
This is useful for audit and debugging, but callers should avoid treating
historical timeline output as current advice.

Deployments that must avoid even soft invalidation can set
`ShibahamaConfig::forgetting.mode` to `ForgettingMode::FlagForReverification`.
In that mode, `Shibahama::invalidate` keeps the memory's valid-time interval and
vector entry intact, then appends a durable `ReverificationFlagged` event for
explicit review. Low-level storage APIs still expose soft invalidation for
deployments that choose the default behavior.

## Server Auth And Namespace Isolation

The optional HTTP server is a thin wrapper over the core API. It supports:

- optional API-key authorization through `Authorization: Bearer ...` or
  `x-api-key`;
- namespace validation with `x-shibahama-namespace`;
- per-namespace memory quotas;
- namespace source-ref prefixes used to filter server recall and Tideline
  snapshots.

Namespace isolation is implemented as application-level source-ref filtering in
the current server. It is not a cryptographic tenant boundary. Deployments that
need hard multi-tenant isolation should use separate stores or add a stronger
authorization layer.

The server does not provide TLS itself. Put it behind a deployment surface that
terminates TLS and controls network access.

## Metadata-Only Request Logging

Server request logs are emitted as JSON to stderr through `log_server_request`.
They include metadata such as:

- event name;
- timestamp;
- method and route;
- namespace;
- principal class;
- HTTP status;
- request-unit and cost counters;
- vector/query dimensions;
- requested and returned counts.

They do not log memory content, raw query context, embeddings, source refs, or
full recall results.

Tideline endpoints return memory/event content to authorized callers by design,
but their request log entries still record only metadata and counts.

## Encryption At Rest

`core/src/encryption.rs` defines an `EncryptionAtRest` trait with `encrypt` and
`decrypt` hooks, plus a `NoopEncryption` implementation used for tests and
extension wiring.

The current default redb store should be treated as plaintext at rest. The
encryption trait is present as an integration point; it is not a claim that
memory content, event logs, snapshots, embeddings, or compacted cold content are
encrypted by default.

If a deployment needs encryption at rest today, use filesystem, volume, or
platform encryption around the store path, and do not treat Shibahama snapshots
as sanitized exports.

## Public Surface Checklist

The current public security-relevant surfaces are:

- `shibahama_core::encryption::EncryptionAtRest`, exported through
  `core/src/lib.rs`, for future encryption-at-rest providers;
- `shibahama_core::encryption::NoopEncryption`, the explicit no-op provider;
- server request logs from `shibahama serve`, emitted through
  `log_server_request` as metadata and cost counters only;
- `ShibahamaConfig::ingest_credence`, which swaps source-kind default credence
  assignments without changing the stored `CredenceTier` ordering invariant;
- `ShibahamaConfig::forgetting`, which can route invalidation requests to
  durable re-verification flags instead of closing valid-time intervals;
- `SanitizingGateway`, the sync recall hook where deployment-specific
  tokenization or redaction can sit before memory text is returned;
- `ProvenanceSigningKey` and signed `Provenance`, which provide optional keyed
  attribution checks for source metadata;
- recall candidate `read_safety_findings`, exposed by the Rust core and
  bindings;
- `why(memory_id)` traces, which expose provenance, credence, tier, currency,
  significance, and audit information for a memory.

This confirms the encryption hook and metadata-only logging behavior are visible
from the repository's public surfaces. It does not mean encryption is active by
default.

## Snapshots And Exports

Snapshots and exports preserve memory content, provenance, event history,
embeddings, graph state, and compacted cold content as applicable. They are
operational artifacts, not redacted audit summaries.

Handle these files as sensitive data. Do not publish benchmark or support
artifacts that were produced from private stores unless their contents were
reviewed separately.

## What Is Not Guaranteed Yet

The current repository does not yet guarantee:

- built-in encryption at rest for the default redb backend;
- hard multi-tenant isolation inside one store;
- a complete prompt-injection defense for all host-agent usage patterns;
- deletion or right-to-erasure semantics, because the core invariant is
  invalidate-not-delete;
- externally audited security properties.

These limits are intentional to state plainly. The current posture is suitable
for local development and controlled evaluation, not for unreviewed production
storage of sensitive data.

## Operational Checklist

For local development:

- keep stores and snapshots out of public repos;
- run `scripts/ci/secrets-scan.sh` before publishing changes;
- inspect `why(memory_id)` when a result looks suspicious;
- prefer explicit source refs for file, tool, and web memories.

For server deployments:

- configure an API key;
- use TLS at the proxy or hosting layer;
- isolate sensitive tenants into separate store files;
- keep stderr logs in a restricted sink;
- monitor anomaly flags for contradiction bursts and suspicious provenance;
- avoid passing recalled memory to an LLM as instructions unless instruction
  recall was intentionally requested.
