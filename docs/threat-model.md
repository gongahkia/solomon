<!-- SPDX-License-Identifier: Apache-2.0 -->

# Threat Model

## Assets

- Firm knowledge content and provenance.
- Client and matter identifiers.
- Kaypoh placeholder mappings.
- Audit journal integrity.
- Model-bound prompts and responses.

## Trust Boundaries

- Solomon store: durable but treated as untrusted on read because retrieved content may contain prompt
  injection or stale legal positions.
- Kaypoh boundary: required for review, pseudonymization, reidentification, and document scrub.
- Model endpoint: receives only sanitized context unless a matter has explicit raw-text opt-in.

## Primary Risks

- Sensitive data egress if Kaypoh is unavailable or bypassed.
- Poisoned model-inferred knowledge outranking firm-authoritative positions.
- Audit tampering after a bad answer.
- Treating a moved dependency as an adjudicated legal conclusion.

## Controls

- Fail-closed boundary adapter.
- Volatile-only mapping storage.
- Credence guardrails and instruction-content separation.
- Hash-chained audit journal.
- Flag-don't-adjudicate currency explanations.

