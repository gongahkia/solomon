<!-- SPDX-License-Identifier: Apache-2.0 -->

# Independent Boundary Audit Checklist

This checklist is written for a reviewer who did not build Solomon. It focuses on the boundary between
firm knowledge, the Solomon boundary, model endpoints, storage, tenants, and audit evidence.

## Scope

- Solomon repository only.
- The boundary source is treated as in-scope Solomon code.
- Audit evidence should be metadata-only unless a test explicitly uses synthetic fixture content.

## Checklist

| Area | Control | Evidence |
|---|---|---|
| Boundary implementation | Solomon includes the local boundary engine. | `src/solomon/boundary/engine/NOTICE`; `docs/boundary-integration.md`; `scripts/boundary_smoke.py` |
| Ingestion review | New knowledge is reviewed before storage and unsafe content can be refused/quarantined. | `src/solomon/api/service.py`; `src/solomon/boundary/solomon.py`; `tests/test_api_client_cli.py` |
| Model egress | Model-bound context is pseudonymized before egress and mappings are volatile. | `tests/test_boundary.py`; `tests/test_security_governance.py` |
| Fail-closed behavior | Boundary engine failure blocks ingestion and model egress paths. | `tests/test_api_client_cli.py`; `tests/test_boundary.py` |
| Raw text discipline | Structured-token mode is the default; raw text requires explicit opt-in. | `docs/trust-boundary.md`; `docs/assumption.md` |
| Prompt injection | Retrieved instructions are separated from facts/positions before prompt assembly. | `tests/test_credence.py`; `tests/test_security_governance.py` |
| Server auth | Server SKU requires an admin key, accepts bearer/API-key credentials, maps requests to admin or tenant principals, and enforces route scopes. | `src/solomon/api/auth.py`; `src/solomon/api/app.py`; `tests/test_security_governance.py`; `tests/test_config_sku.py` |
| Tenant isolation | Server SKU registers tenants, enforces active/suspended state, accepts tenant-specific key hashes, and namespaces data and journals by `x-tenant-id`. | `src/solomon/api/app.py`; `src/solomon/api/tenancy.py`; `tests/test_api_client_cli.py` |
| Contestability | Contests demote and stale-flag knowledge, proposed corrections stay quarantined until FirmAuthoritative affirm, and contests propagate to dependents. | `src/solomon/api/service.py`; `tests/test_contestability.py` |
| Query budget | Recall can cap estimated context tokens before sanitisation/model assembly. | `src/solomon/orchestrator/retrieval.py`; `tests/test_retrieval.py` |
| Audit content | Audit journal stores ids, hashes, states, and metadata, not privileged prompt content. | `src/solomon/audit/journal.py`; `tests/test_audit.py` |
| Verification signature | Human verification can be HMAC-attested without storing content. | `tests/test_audit.py`; `tests/test_api_client_cli.py` |
| Right to erasure | Erasure creates tombstones while preserving audit integrity. | `docs/erasure.md`; `tests/test_audit.py` |
| Optional Office clients | Office surfaces remain thin clients; Solomon gets only reviewed/redacted text. | `docs/office-frontends.md` |

## Reviewer Commands

```bash
uv run ruff check .
uv run mypy src tests scripts examples/scenarios/stale-house-view/run.py benchmarks/performance_budget.py
uv run mypy examples/scenarios/internal-supersession/run.py
uv run pytest tests/test_boundary.py tests/test_security_governance.py tests/test_audit.py tests/test_api_client_cli.py
```

## Audit Questions

- Can any path send raw privileged text to a remote model when `zero_egress_mode=true`?
- Can tenant A recall, inspect, or audit tenant B data on the server SKU?
- Does a suspended tenant lose access without deleting its stored data?
- Can a read-only tenant key call a mutating route such as `/ingest`?
- Are diagnostics and tenant lifecycle routes reachable only with the server admin key?
- Can a lower-tier or model-inferred actor override a human-affirmed contested correction?
- Does contesting an item stale-flag its dependents without deleting the original?
- Does any audit export contain prompt text, document body text, client names, or boundary mappings?
- Does review-mode recall clearly distinguish stale/superseded knowledge from default live recall?
- Are optional Office front-ends unable to bypass boundary review before calling Solomon?
