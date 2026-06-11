<!-- SPDX-License-Identifier: Apache-2.0 -->

# Independent Boundary Audit Checklist

This checklist is written for a reviewer who did not build Solomon. It focuses on the boundary between
firm knowledge, Kaypoh, model endpoints, storage, tenants, and audit evidence.

## Scope

- Solomon repository only.
- Kaypoh is treated as an external sibling dependency and is not modified by this audit.
- Audit evidence should be metadata-only unless a test explicitly uses synthetic fixture content.

## Checklist

| Area | Control | Evidence |
|---|---|---|
| Kaypoh import boundary | Solomon imports or calls Kaypoh; it does not fork Kaypoh source. | `docs/kaypoh-integration.md`; `scripts/kaypoh_smoke.py`; `tests/test_boundary.py` |
| Ingestion review | New knowledge can be reviewed before storage and unsafe content can be refused/quarantined. | `src/solomon/boundary/kaypoh.py`; `tests/test_boundary.py` |
| Model egress | Model-bound context is pseudonymized before egress and mappings are volatile. | `tests/test_boundary.py`; `tests/test_security_governance.py` |
| Fail-closed behavior | Kaypoh outage blocks egress paths that require the boundary. | `tests/test_boundary.py` |
| Raw text discipline | Structured-token mode is the default; raw text requires explicit opt-in. | `docs/trust-boundary.md`; `docs/assumption.md` |
| Prompt injection | Retrieved instructions are separated from facts/positions before prompt assembly. | `tests/test_credence.py`; `tests/test_security_governance.py` |
| Tenant isolation | Server SKU namespaces data and journals by `x-tenant-id`. | `src/solomon/api/app.py`; `tests/test_api_client_cli.py` |
| Query budget | Recall can cap estimated context tokens before sanitisation/model assembly. | `src/solomon/orchestrator/retrieval.py`; `tests/test_retrieval.py` |
| Audit content | Audit journal stores ids, hashes, states, and metadata, not privileged prompt content. | `src/solomon/audit/journal.py`; `tests/test_audit.py` |
| Verification signature | Human verification can be HMAC-attested without storing content. | `tests/test_audit.py`; `tests/test_api_client_cli.py` |
| Right to erasure | Erasure creates tombstones while preserving audit integrity. | `docs/erasure.md`; `tests/test_audit.py` |
| Optional Office clients | Kaypoh Office surfaces remain thin clients; Solomon gets only reviewed/redacted text. | `docs/office-frontends.md` |

## Reviewer Commands

```bash
uv run ruff check .
uv run mypy src tests scripts examples/stale-house-view/run.py benchmarks/performance_budget.py
uv run mypy examples/internal-supersession/run.py
uv run pytest tests/test_boundary.py tests/test_security_governance.py tests/test_audit.py tests/test_api_client_cli.py
```

## Audit Questions

- Can any path send raw privileged text to a remote model when `zero_egress_mode=true`?
- Can tenant A recall, inspect, or audit tenant B data on the server SKU?
- Does any audit export contain prompt text, document body text, client names, or Kaypoh mappings?
- Does review-mode recall clearly distinguish stale/superseded knowledge from default live recall?
- Are optional Office front-ends unable to bypass Kaypoh review before calling Solomon?
