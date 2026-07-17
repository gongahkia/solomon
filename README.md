# Close Enough

Local, deterministic terminal repair hints. The current slice supports command, Git subcommand, and path typo suggestions with configurable hint, interrupt, rewrite, and off modes.

License: GPL-3.0-only. The complete license text is required before the first release artifact.

```sh
go build ./cmd/close-enough
./close-enough init --shell zsh >> ~/.zshrc
./close-enough check --command 'gti status'
```

`close-enough` never sends command data over the network by default and does not auto-apply risky transformations.

Plain diagnostics use color only on a terminal; pass `check --color=never` to disable it explicitly, or `--color=always` to force it.

Pass `check --format=plain --screen-reader` for structured, ANSI-free diagnostics without visual diff markers.

JSON diagnostics include stable `cause_key` and `consequence_key` fields alongside their default English text.

Plain diagnostics present confidence as high, medium, low, or unknown; set `display.confidence` to `false` to hide it.

Risk output includes a static rationale and never includes raw command arguments.

Configuration is read from `$XDG_CONFIG_HOME/close-enough/config.json`; an unset or relative `XDG_CONFIG_HOME` falls back to `$HOME/.config/close-enough/config.json`.

Session overrides are limited to `CLOSE_ENOUGH_MODE`, `CLOSE_ENOUGH_AUTO_APPLY_SAFE`, `CLOSE_ENOUGH_LOCAL_HISTORY_ENABLED`, `CLOSE_ENOUGH_REGISTRY_ENABLED`, and `CLOSE_ENOUGH_AUTO_UPDATE_ENABLED`; booleans must be `true` or `false`.

Project configuration requires `.close-enough/config.json` and a same-directory `trusted` marker owned by the current user; Unix markers must be `0600` and their directory must not be group- or world-writable.

Registry and auto-update features are disabled by default; auto-update requires explicit registry enablement as well.

Optional local-history encryption keys use an injected OS credential-store backend only; no file fallback is provided.

History ranking is disabled by default and stores only SHA-256 command keys through an injected local backend after opt-in.

Startup rejects privileged execution, relative or empty PATH entries, and group- or world-writable working directories; `close-enough doctor` reports these findings without blocking.

Secure writes and trusted project configuration require platform support for atomic replacement, restrictive permissions, and ownership verification; unsupported platforms fail closed.

Release builds report injected version and commit metadata through `close-enough version`.

Run the local CI target with `make ci`.

Exit codes are stable: `0` success, `1` unexpected internal failure, `2` invalid CLI usage, `3` configuration failure, `4` invalid command or pack input, and `5` local operation failure.
