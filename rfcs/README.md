# Shisa RFCs

RFCs are required for changes to the wire protocol, plugin API, security model, theme/rendering spec, or governance process.

PRs under public RFC review carry the `rfc-comment-window` label. The label starts a 14-day gate; CI passes after the label has been present for 14 days.

Accepted RFCs must also have a matching `docs/internals/rfc-NNNN-*.md` decision summary. CI enforces this with `scripts/rfc-internals-gate.sh`.

| RFC | Title | Status | Area |
| --- | --- | --- | --- |
| [0000](0000-template.md) | Template | Active | core |
| [0001](0001-daemon-wire-protocol.md) | Daemon Wire Protocol | Accepted | wire protocol |
| [0002](0002-module-execution-classes.md) | Module Execution Classes | Accepted | renderer |
| [0003](0003-lua-plugin-capability-manifest.md) | Lua Plugin Capability Manifest | Accepted | plugin API |
| [0004](0004-cache-invalidation-rules.md) | Cache Invalidation Rules | Accepted | cache |
| [0005](0005-wire-protocol-v1.md) | Wire Protocol v1 | Accepted | wire protocol |
| [0006](0006-per-project-config-layering.md) | Per-Project Config Layering | Draft | config |
