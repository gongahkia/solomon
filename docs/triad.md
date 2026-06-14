<!-- SPDX-License-Identifier: Apache-2.0 -->

# Boundary + Currency + Audit

Solomon is organized around three internal layers:

```text
Boundary -> review, pseudonymize, reidentify, scrub, fail closed
Currency -> dependencies, supersession, verification, stale flags
Audit    -> metadata-only evidence of what happened and why
```

The layers are deliberately separate. The boundary decides what can cross a model boundary. The currency
engine decides whether firm knowledge needs re-verification. The audit layer records evidence without storing
privileged prompt or document text.
