# Landing Copy

## One-line pitch

A daemon-backed, async-first, cross-shell prompt built to keep shell input responsive.

## Hero copy

Shisa pre-renders your prompt in a background daemon so your shell stays responsive in huge repos, nix shells, cloud contexts, and plugin-heavy workflows.

## Primary proof points

- Warm prompt render target: p99 under 2 ms.
- Fallback prompt target: under 5 ms when the daemon is unreachable.
- Filesystem-watch cache invalidation for git, language versions, and cloud context.
- Capability-gated Lua plugins with no network access unless explicitly trusted.
- Zero telemetry.

## Install placeholder

```sh
curl -sSL https://shisa.sh/install | sh
```

The installer is served from `packaging/install.sh` and verifies the release archive plus SHA-256 file against Sigstore bundles before installing binaries.
