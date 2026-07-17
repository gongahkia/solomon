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

Shell adapters render at most five hint or post-failure diagnostics per loaded shell session; interrupt and rewrite safety behavior is never rate-limited.

Adapters also suppress repeated hint suggestions within a loaded shell session.

Configuration is read from `$XDG_CONFIG_HOME/close-enough/config.json`; an unset or relative `XDG_CONFIG_HOME` falls back to `$HOME/.config/close-enough/config.json`.

Session overrides are limited to `CLOSE_ENOUGH_MODE`, `CLOSE_ENOUGH_AUTO_APPLY_SAFE`, `CLOSE_ENOUGH_LOCAL_HISTORY_ENABLED`, `CLOSE_ENOUGH_REGISTRY_ENABLED`, and `CLOSE_ENOUGH_AUTO_UPDATE_ENABLED`; booleans must be `true` or `false`.

Session overrides affect only the invoking process and never modify configuration files.

Use `close-enough rule list|add|update|remove` to manage global exact-command exceptions; matching exceptions suppress diagnostics and never alter command execution.

Use `close-enough inspect-decision --command '<command>'` for full structured diagnostics and redaction-safe command diffs.

`close-enough doctor` includes remediation hints for shell adapter limitations.

Pack schema v1 is strictly compatible only with schema version `1`; legacy and future schemas are rejected without migration.

Pack and rule identifiers use lowercase kebab case; pack versions use SemVer 2.0.

Pack matchers are compiled as in-process regular expressions and never execute manifest text.

Transformation templates allow literal text, `$$`, and in-range `$1` capture references only.

Explanation templates use the same capture syntax and reject control characters.

Every pack rule must declare a risk class and static risk rationale.

Pack fixture schema v1 runs declarative command/input cases against expected rule IDs without executing manifest content.

Project configuration requires `.close-enough/config.json` and a same-directory `trusted` marker owned by the current user; Unix markers must be `0600` and their directory must not be group- or world-writable.

Registry and auto-update features are disabled by default; auto-update requires explicit registry enablement as well.

Optional local-history encryption keys use an injected OS credential-store backend only; no file fallback is provided.

History ranking is disabled by default and stores only SHA-256 command keys through an injected local backend after opt-in.

Startup rejects privileged execution, relative or empty PATH entries, and group- or world-writable working directories; `close-enough doctor` reports these findings without blocking.

Secure writes and trusted project configuration require platform support for atomic replacement, restrictive permissions, and ownership verification; unsupported platforms fail closed.

Release builds report injected version and commit metadata through `close-enough version`.

Run the local CI target with `make ci`.

Exit codes are stable: `0` success, `1` unexpected internal failure, `2` invalid CLI usage, `3` configuration failure, `4` invalid command or pack input, and `5` local operation failure.
