<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0008: Audit Journal Design

## Status

Accepted.

## Context

Solomon must prove what was known, when, why an item was flagged, and what crossed the model boundary,
without storing privileged prompt content in the audit log.

## Decision

Solomon uses an append-only JSONL journal with hash chaining. Entries store metadata only: item ids,
currency states, dependency ids, prompt hashes, endpoint decisions, and verification events.

## Consequences

Tampering is detectable by replaying the chain. Audit packs export the journal plus a manifest hash.
Content must remain in the knowledge store and boundary layer, not in audit payloads.

