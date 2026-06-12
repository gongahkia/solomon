# Horizontal Scale

Shibahama is in-process first. The default deployment shape is one embedded
store and one vector index in the caller's process. Horizontal scale is
therefore a routing and tenancy story around many small stores, not a hidden
distributed database inside the core.

## Current Server Boundary

`shibahama serve` already exposes the primitives needed for namespace sharding:

- `x-shibahama-namespace` selects a namespace for each request;
- namespace names are validated before use;
- writes prefix source refs with `shibahama-server:namespace=<name>;`;
- recall uses the same prefix as a `RecallRequest::with_source_ref_prefix`
  filter;
- readiness and inspect endpoints report per-namespace memory counts;
- `--max-memories-per-namespace` bounds one namespace inside a server process;
- request logs include metadata and namespace, but not memory content.

This is application-level isolation inside one store. It is useful for local
multi-project agents and small team deployments, but it is not the scale-out
boundary.

## Shard By Namespace

For horizontal scale, route each namespace to exactly one shard:

1. Put a thin router in front of `shibahama serve`.
2. Hash the validated namespace, preferably with rendezvous hashing so shard
   membership can change with limited movement.
3. Run one Shibahama server process per shard, each with its own store path and
   vector index.
4. Forward the original `x-shibahama-namespace` header to the chosen shard.
5. Keep namespace quotas enforced at the shard and optionally at the router.

Each shard remains simple: one embedded redb store, one active vector index, and
the same append-only event log invariants. Moving a namespace means exporting
that namespace's store data or replaying its event stream into another shard,
then updating the router's shard map.

## Operational Rules

- Keep a namespace sticky to one shard for all writes and reads.
- Prefer separate store files for sensitive tenants or any namespace that needs
  harder isolation than source-ref filtering.
- Scale reads by adding shards and moving namespaces, not by sharing one store
  across many writers.
- Treat graph traversal and Tideline snapshots as namespace-local unless a
  caller explicitly builds a cross-namespace application layer.
- Back up and restore at shard granularity unless a namespace export tool is
  added later.

## What This Does Not Claim

The current repo does not implement:

- distributed transactions across shards;
- cross-shard graph traversal;
- a global vector index;
- automatic namespace migration;
- cryptographic tenant isolation inside one store;
- multi-writer replication for a single namespace.

Those are intentionally outside the embedded-core promise. The scale target is
many independent namespace shards with clear routing, metadata-only operations,
and simple failure domains.
