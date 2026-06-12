<!-- SPDX-License-Identifier: Apache-2.0 -->

# Assumptions

- Solomon is self-contained; the boundary engine is vendored from Kaypoh and pinned in
  `src/solomon/boundary/engine/NOTICE`.
- Kaypoh and Solomon are operated by the same firm boundary owner.
- Remote model use means ZDR-equivalent contractual terms and sanitized context only.
- SQLite is the default local SKU store; server deployments may replace it with Postgres behind the same
  event-log contract by installing `solomon[server]` and setting `SOLOMON_DATABASE_URL`.
