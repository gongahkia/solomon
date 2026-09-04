<!-- SPDX-License-Identifier: Apache-2.0 -->

# Threat Model

This is a design threat model for Solomon's documented local and single-host profiles. It distinguishes controls that
exist in the repository from deployment and host responsibilities. It is not a penetration test, legal-security
assessment, production certification, or assertion that the listed controls eliminate the risks below.

## Assets

- Firm knowledge content and provenance.
- Client and matter identifiers.
- Server admin and tenant API credentials.
- MCP principals, their tool scopes, and matter/client grants.
- Boundary placeholder mappings.
- Audit journal integrity.
- Model-bound prompts and responses.
- Backups, restore plans, and durable-operation records.

## Actors and trust boundaries

| Boundary | What Solomon enforces | Residual responsibility |
| --- | --- | --- |
| Human curator/reviewer → Solomon | Role/scope checks, governed assertion and verification state machines, audit attribution. | Identity proofing, separation-of-duties assignment, legal judgement, and source selection are operator controls. |
| MCP host → Solomon | Bound-principal scopes, matter/client restrictions, tool permissions, rate limits, boundary review, and metadata-only call audit. | The host must authenticate its user, request only authorized scope, gain consent where necessary, and decide which tools its model may invoke. |
| Solomon store → host/model | Recall excludes non-live items by default; preflight output passes boundary review; instruction-like content is not load-bearing context. | The host must treat all returned text and explanations as data, not executable instructions, and must not silently fall back to another stale corpus. |
| Solomon → model endpoint | Designated model egress is pseudonymized and fail-closed unless explicit raw-text opt-in is configured. | Endpoint retention, training, subprocessors, network security, privilege analysis, and model behavior are outside Solomon. |
| SQLite/PostgreSQL/JSONL → operator | Defined partial operations have journalled retry, inspection, and guarded reconciliation; checkpoint/restore is rehearsed for the documented profile. | The stores do not share a distributed transaction; operators own access, keys, backup custody, and ambiguous recovery decisions. |

## Priority risks and treatment

| Risk | Repository control | What remains unproven or external |
| --- | --- | --- |
| A stale internal position reaches a draft through the Solomon path | Confirmed dependency changes mark affected items review-due; normal recall/preflight excludes non-live items. | A host can ignore or bypass Solomon, a dependency can be missing, and a `Live` item is not a correctness determination. |
| A host/model obtains mutation authority from untrusted content | MCP tools have roles/scopes and read-only annotations; the reference host uses a fixed read-only allowlist. | A host that exposes write tools to a model needs its own explicit approval and authorization model. |
| Caller identity or scope is spoofed | Bound MCP identity overrides caller-provided identity; restricted principals require authorized matter/client scope. | Stdio identity is local process trust configuration; an HTTP/SSE deployment needs a real bearer-to-principal resolver. |
| Retrieved content attempts prompt injection or changes host control flow | Stored content is treated as untrusted; instruction-role content is excluded from load-bearing use; output boundary review can withhold context. | This is not a complete prompt-injection defence or an adversarial evaluation of a host/model pair. |
| Sensitive content leaves the intended route | Boundary review/pseudonymization and raw-text opt-in controls exist for designated paths. | Detection coverage, user consent, endpoint behavior, and cross-border/legal obligations are not certified. |
| Audit evidence is altered or a crash leaves projections partial | Hash-chain verification, durable operations, scoped inspection, and guarded repair cover defined states. | No external immutable ledger, distributed ACID transaction, or universal recovery guarantee exists. |
| Credentials, backups, or repair plans are misused | Credentials are scoped; production restore is guarded; backup guidance separates secret handling. | Key management, storage access, rotation, and incident response are deployment-owned. |
| Host or tool calls exhaust resources | The MCP runtime has per-principal token-bucket limiting and bounded request inputs. | Capacity, multi-process coordination, traffic abuse, and production rate limits are not load-tested claims. |

## Required host posture

For a model-facing use, a compatible host should bind the user/principal before it calls Solomon, pass explicit scope,
maintain a non-model-controlled read-only tool allowlist, inject only successful preflight items, and send failures to a
human workflow rather than silently retrieving stale substitutes. It should log its final reuse/withhold decision with
the returned Solomon audit reference. The reference implementation in
[`guides/reference-host-integration.md`](./guides/reference-host-integration.md) demonstrates that bounded policy
through real MCP stdio transport.

The Model Context Protocol places consent and tool-safety obligations on implementers, including user understanding of
tools before authorization. OWASP describes excessive agency as damage arising when LLM-driven systems have too much
functionality, permission, or autonomy. These sources motivate the design; they do not validate Solomon's controls.

## Existing controls

- Fail-closed boundary adapter.
- Volatile-only mapping storage.
- Credence guardrails and instruction-content separation.
- Server auth requires an admin key, supports bearer/API-key credentials, hashes tenant keys, and enforces
  route scopes for tenant read, tenant write, tenant management, and diagnostics.
- Hash-chained audit journal.
- Flag-don't-adjudicate currency explanations.

## Out of scope and verification status

Solomon has no claim of resistance to all prompt injection, malware, compromised hosts, malicious administrators,
database deletion, endpoint exfiltration, or physical-media recovery. It does not prove that a host used a returned
decision, that a reviewer made a correct legal judgement, or that a retention marker erased copies outside its local
query path. Its repository tests exercise specific authorization, scope, boundary, audit, recovery, and transport
behaviors; they are not a security certification or external security review.
