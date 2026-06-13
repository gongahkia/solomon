<!-- SPDX-License-Identifier: Apache-2.0 -->

# Threat Model

## Assets

- Firm knowledge content and provenance.
- Client and matter identifiers.
- Server admin and tenant API credentials.
- Kaypoh placeholder mappings.
- Audit journal integrity.
- Model-bound prompts and responses.

## Trust Boundaries

- Solomon store: durable but treated as untrusted on read because retrieved content may contain prompt
  injection or stale legal positions.
- Kaypoh boundary: required for review, pseudonymization, reidentification, and document scrub.
- Model endpoint: receives only sanitized context unless a matter has explicit raw-text opt-in.
- Server API: authenticates admin and tenant principals before tenant-scoped storage, diagnostics, or
  lifecycle operations are reachable.

## Primary Risks

- Sensitive data egress if Kaypoh is unavailable or bypassed.
- Poisoned model-inferred knowledge outranking firm-authoritative positions.
- Audit tampering after a bad answer.
- Tenant credential misuse or accidental use of an admin key in a thin client.
- Treating a moved dependency as an adjudicated legal conclusion.

## Controls

- Fail-closed boundary adapter.
- Volatile-only mapping storage.
- Credence guardrails and instruction-content separation.
- Server auth requires an admin key, supports bearer/API-key credentials, hashes tenant keys, and enforces
  route scopes for tenant read, tenant write, tenant management, and diagnostics.
- Hash-chained audit journal.
- Flag-don't-adjudicate currency explanations.
