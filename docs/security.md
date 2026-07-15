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
  snapshots;
- namespace attributes used to filter server graph rows.

Namespace isolation is implemented as application-level source-ref filtering in
the current server. It is not a cryptographic tenant boundary. Deployments that
need hard multi-tenant isolation should use separate stores or add a stronger
authorization layer.

The server does not provide TLS itself. Put it behind a deployment surface that
terminates TLS and controls network access.

## Metadata-Only Request Logging

Server request logs are emitted as schema-versioned JSON to stderr. Each record
includes:

- schema version, event name, timestamp, component, and operation;
- a keyed, non-reversible scope ID rather than the namespace;
- principal class;
- duration and HTTP status;
- stable error code when unsuccessful;
- numeric request-unit, count, and dimension metrics only.

They do not log memory content, raw query context, embeddings, source refs,
credentials, or raw identity claims.

## OpenTelemetry Boundaries

Build the core or CLI with the `opentelemetry` feature to emit standard spans
and the `shibahama.operation.count` counter through the host-installed global
OpenTelemetry provider. The feature is disabled by default. Instrumentation has
only fixed component, operation, and outcome attributes; it never receives
memory content, scope IDs, source refs, credentials, or identity claims.

Tideline endpoints return memory/event content to authorized callers by design,
but their request log entries still record only metadata and counts.

## Encryption At Rest

`core/src/encryption.rs` defines an `EncryptionAtRest` trait with `encrypt` and
`decrypt` hooks. `NoopEncryption` is the default provider used by
`RedbMemoryStore::open`, so the default redb store is plaintext at rest.

Rust callers can opt in with `RedbMemoryStore::open_with_encryption` and
`Aes256GcmEncryption`. The encrypted provider wraps table payload values for the
event log, materialized memory rows, embeddings, compacted cold content, graph
entities, and graph relations. It authenticates the table name and row key as
AEAD associated data, so a copied payload cannot be silently replayed into a
different table/key context. Opening an encrypted store with the wrong key, or
with the plaintext provider, fails closed during recovery.

This is payload encryption, not a complete secret-management system. Shibahama
does not generate, persist, rotate, unwrap, or escrow encryption keys. The redb
file can still expose database metadata such as table names, row keys, file size,
and write patterns. Deployments that need stronger operational guarantees should
combine the provider with filesystem, volume, or platform encryption.

Plaintext snapshot export is disabled for encrypted stores. Snapshots from
plaintext stores remain sensitive operational artifacts, not sanitized audit
summaries.

## Public Surface Checklist

The current public security-relevant surfaces are:

- `shibahama_core::encryption::EncryptionAtRest`, exported through
  `core/src/lib.rs`, for encryption-at-rest providers;
- `shibahama_core::encryption::NoopEncryption`, the explicit no-op provider;
- `shibahama_core::encryption::Aes256GcmEncryption`, the optional AES-256-GCM
  provider for encrypted redb payloads;
- server request logs from `shibahama serve`, emitted through
  `log_server_request` as versioned, scope-safe operational records only;
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

This confirms optional payload encryption and metadata-only logging behavior are
visible from the repository's public surfaces. It does not mean encryption is
active by default.

## Snapshots And Exports

Snapshots and exports preserve memory content, provenance, event history,
embeddings, graph state, and compacted cold content as applicable. They are
operational artifacts, not redacted audit summaries.

Handle these files as sensitive data. Do not publish benchmark or support
artifacts that were produced from private stores unless their contents were
reviewed separately.

## What Is Not Guaranteed Yet

The current repository does not yet guarantee:

- encryption at rest for the default redb backend;
- built-in encryption key management or rotation;
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
