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
| [0007](0007-marketplace-2.md) | Marketplace 2.0 | Draft | plugin marketplace |
| [0008](0008-daemon-lifecycle.md) | Daemon Lifecycle Across SSH/Containers/nix-shell/tmux/sudo | Accepted | daemon lifecycle |
| [0010](0010-ai-plugin-capability.md) | Local AI Plugin Capability | Draft | AI, plugin security |
| [0011](0011-right-prompt.md) | Right Prompt | Draft | shell integration, renderer |
| [0012](0012-self-observability-exporter.md) | Local Self-Observability Exporter | Draft | daemon observability, security |
| [0013](0013-reactive-updates.md) | Reactive Prompt Updates | Draft | daemon lifecycle, shell integration |
