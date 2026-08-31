<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0006: Credence Taxonomy

## Status

Accepted.

## Context

Firm knowledge can come from partner-signed positions, associate work product, matter documents, external
feeds, or model output. Treating those sources as equivalent creates a poisoning path where a plausible
model-generated statement can outrank a firm-authoritative position.

## Decision

Solomon uses four tiers: `FirmAuthoritative`, `Verified`, `ModelInferred`, and `Unverified`.
`ModelInferred` and `Unverified` content cannot outrank `FirmAuthoritative` content at equal relevance and
cannot be presented as settled load-bearing output without verification.

## Consequences

Ranking, prompt assembly, and verification gates must carry credence metadata. Promotions and demotions are
audited with actor and reason.

