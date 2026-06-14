<!-- SPDX-License-Identifier: Apache-2.0 -->

# ADR 0004: Solomon Owns The Boundary

## Status

Accepted.

## Context

Solomon needs a sanitising boundary for `/review`, `/pseudonymize`, `/reidentify`, document scrub, strict
jurisdiction profiles, and local/server deployment. That boundary should be a first-class Solomon subsystem,
not a separately branded dependency.

## Decision

Solomon keeps the local boundary implementation under `src/solomon/boundary/engine/` and exposes it through
`src/solomon/boundary/solomon.py`.

| Concern | Solomon behavior |
|---|---|
| Ingestion safety gate | Call `/review` before storage. |
| Outbound model context | Call `/pseudonymize`; retain mapping only in volatile memory. |
| Inbound model response | Call `/reidentify`; flush the volatile mapping after use. |
| Document file ingestion | Call `/documents/scrub` before extraction. |
| Boundary unavailable | Fail closed. |

## Consequences

Solomon's CI includes boundary smoke and fixture coverage. Unit tests may still use fakes for edge cases, but
the default service path uses the in-process Solomon boundary.
