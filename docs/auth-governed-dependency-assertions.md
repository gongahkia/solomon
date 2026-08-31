# Governed dependency assertion authorization

Authorization is enforced in the service façade before the lifecycle action, then source/target scope is checked
again while resolving the assertion. A scope mismatch does not disclose the assertion or target.

| Action | Required service permission | Scope and duty rule | Graph effect |
| --- | --- | --- | --- |
| create | `curate` | source document must be registered and bound to the source item; target must be registered and match matter/client scope | none |
| list, get, history | `read` | requested matter/client must match the assertion source item | none |
| confirm, reject, defer | `review` | requester scope must match; the creator cannot decide the same assertion | only confirm may create one provenance-linked edge |
| withdraw | `curate` | requester scope must match; only pending/deferred state is eligible | none |
| source revision re-verification | ingestion authorization | document revision lineage determines affected assertions | marks re-verification; preserves prior evidence and edges |

The assertion projection records the declared creator and actor-attributed audit events. Default separation of duties
is an application control, not an identity-provider replacement: deployments must bind actual identities and service
permissions through their configured authorization layer. MCP retains a scoped read projection only; it cannot mutate
assertions.
