<!-- SPDX-License-Identifier: Apache-2.0 -->

# Right-to-Erasure Handling

Solomon reconciles erasure requests with the supersede-not-delete invariant by separating legal audit
evidence from queryable knowledge.

- Queryable personal data should be redacted, pseudonymized, retired, or access-restricted according to
  firm policy and applicable law.
- The audit journal records a tombstone containing a hash of the subject reference, lawful basis, actor,
  and timestamp.
- The tombstone proves handling occurred without deleting the historical event chain.
- Raw deletion of knowledge rows is not the erasure mechanism; it would break the "what did we know and
  when" evidence chain.

