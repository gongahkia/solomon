<!-- SPDX-License-Identifier: Apache-2.0 -->

# Right-to-Erasure Handling

Solomon reconciles erasure requests with the supersede-not-delete invariant by separating legal audit
evidence from queryable knowledge.

- An operator submits an item-, matter-, or client-scoped request with a subject reference and lawful basis.
- An active matching legal hold blocks the entire request. Releasing the hold permits a later request or retention run.
- A completed request retires each current item and replaces its queryable content with a retention marker.
- The audit journal records subject-reference and scope hashes, lawful basis, actor, decision, correlation ID, and a
  tombstone. It does not record the raw subject reference.
- Historical event payloads remain to preserve the hash-chained "what did we know and when" evidence chain. This is
  logical erasure, not a claim of physical-media sanitization, backup deletion, or legal compliance.
- `SOLOMON_RETENTION_DEFAULT_DAYS` enables age-based selection only when an administrator invokes
  `POST /retention/run`; it does not run automatically.
