# Pack Status

Pack lifecycle:

| State | Meaning | Exit criteria |
| --- | --- | --- |
| `incubation` | Experimental plugin pack or template. | Basic docs, smoke test, owner. |
| `graduated` | Supported pack with stable manifest/API usage. | Benchmarks, compatibility docs, release notes. |
| `vetted` | Maintainer-reviewed pack with a local verified marker. | Signed bundle, capability review, security owner. |
| `eol` | Deprecated or unsupported pack. | Migration path or removal note. |
| `supported core profile` | Release-supported configuration built into Shisa. | Stable profile name, deterministic tests, capability and no-network documentation. |

Current packs:

| Pack | State | Owner | Issue tracker | Notes |
| --- | --- | --- | --- | --- |
| `shisa.vcs` | incubation | core | core repo | jj/sapling core support plus fossil/pijul/bazaar community templates. |
| `shisa.cloud` | supported core profile | core | core repo | `cloud` and `infra` are bounded command-aware profiles using local cached provider context; no marketplace or independent pack bundle. |
| `shisa.ai` | incubation | core | core repo | Optional local-first hint pack; outside core. |
| community templates | incubation | community | template owner repo | Templates distributed from their owner repositories. |

## Issue Routing

Incubation packs are triaged in the core repo until they have a stable owner, release cadence, and issue tracker.

A pack cannot move to `graduated` unless its row lists a pack-level issue tracker. After graduation:

- pack module bugs, feature requests, and pack-specific performance reports move to the pack repo
- core keeps host API, protocol, security, and cross-pack compatibility issues
- misplaced core issues should be closed with a link to the pack tracker or transferred when GitHub supports it
- pack owners must include core issue links when a pack bug exposes a core host/API defect

## Pack Performance Budgets

`zig build bench` emits a `packs` JSON object and fails when any deterministic pack budget is exceeded. The standard CI build runs it on supported operating systems.

| Pack | PR gate | Budget |
| --- | --- | --- |
| `shisa.vcs` | `packs.shisa.vcs.fixture_batch_ns` | <= 500 ms for 1000 VCS fixture parse/format passes. |
| `shisa.cloud` | `packs.shisa.cloud.cloud_ctx_cold_ns`, `packs.shisa.cloud.cloud_ctx_warm_avg_ns` | cold < 30 ms; warm average < 1 ms. |
| `shisa.ai` | `packs.shisa.ai.redact_batch_ns` | <= 80 ms for 1000 local redaction passes. |

Pack changes that add a prompt path, parser, cache reader, local model pre/post-processing path, or official template must update this table and the matching `src/bench.zig` budget in the same change.

Status changes require a changelog entry and capability review when capabilities change.

Adding a new official pack, graduating a pack, expanding pack capabilities, or changing a supported core profile must update local capability docs in the same change.
