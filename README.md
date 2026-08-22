# Close Enough

Local, deterministic terminal repair. Close Enough diagnoses likely command mistakes before submission and after supported failures, then presents a risk-classified hint. It supports command, Git subcommand, and path typo suggestions with configurable hint, interrupt, rewrite, and off modes.

License: GPL-3.0-only. See [LICENSE](LICENSE).

## Quick start

Close Enough currently supports source installation with Go 1.24 or newer. From a clone of this repository:

```sh
go install ./cmd/close-enough

# add $(go env GOPATH)/bin to PATH first if Go has not already done so
eval "$(close-enough init --shell zsh)"

# make the Zsh integration persistent
close-enough init --shell zsh >> ~/.zshrc

close-enough check --format plain --command 'git sttaus'
```

New and migrated configurations are hint-only. A bundled safe rewrite requires both `mode=rewrite` and `auto_apply_safe=true` as an explicit opt-in; it edits the shell buffer, requires another Enter to submit, and can be undone with Ctrl-G.

Zsh is first-class. Fish and PowerShell support the same repair modes, with their adapter limitations reported by `close-enough doctor`; PowerShell requires PSReadLine. Bash shell integration is intentionally unavailable because the retired adapter could evaluate a command buffer and replace the user's DEBUG trap. The standalone `check` command remains available from Bash.

## How this differs from The Fuck

The projects share the command-repair problem space, but Close Enough is designed as a conservative shell-integrated assistant rather than a command replay tool.

| | The Fuck | Close Enough |
| --- | --- | --- |
| Interaction | Run an explicit alias after a command fails; choose a corrected command to execute. | Diagnose before submission and after supported failures; default to a non-blocking hint. |
| Failure data | Matches extensible Python rules against command output and shell history. | Extracts bounded, allow-listed evidence for supported tools, redacts it before matching, and never persists command history. |
| Applying a repair | Can execute the selected correction. | Rewrites only explicitly opted-in, bundled `safe` repairs in the shell buffer; high-risk and installed-pack repairs are never auto-applied. |
| Extension model | Python rules, including third-party packages. | Declarative packs with strict schema validation, explicit risk metadata, and Ed25519 publisher trust. |
| Shell command | Uses the `fuck` trigger alias in its recommended shell setup. | Uses only `close-enough`; it does not create a `fuck` or `thefuck` alias. |

This lets both tools be installed while users evaluate Close Enough without alias conflicts. Close Enough's position should remain: explain a deterministic, locally evaluated repair before changing a command, and make any command-buffer rewrite explicit, reversible, and constrained by risk.

## Installation from a release

The release workflow is configured to produce signed archives and installers for macOS, Linux, and Windows. The verified install path is below; use it once a versioned release is available.

`close-enough` does not send command data over the network during diagnosis. Plain diagnostics use color only on a terminal; pass `check --color=never` to disable it explicitly, or `--color=always` to force it.

Pass `check --format=plain --screen-reader` for structured, ANSI-free diagnostics without visual diff markers.

JSON diagnostics include stable `cause_key` and `consequence_key` fields alongside their default English text.

Plain diagnostics present confidence as high, medium, low, or unknown; set `display.confidence` to `false` to hide it.

Risk output includes a static rationale and never includes raw command arguments.

Shell adapters render at most five hint or post-failure diagnostics per loaded shell session; interrupt and rewrite safety behavior is never rate-limited. Bash is intentionally unsupported: use the standalone CLI from Bash, or initialize Zsh, Fish, or PowerShell.

Adapters also suppress repeated hint suggestions within a loaded shell session.

Configuration is read from `$XDG_CONFIG_HOME/close-enough/config.json`; an unset or relative `XDG_CONFIG_HOME` falls back to `$HOME/.config/close-enough/config.json`.

Session overrides are limited to `CLOSE_ENOUGH_MODE`, `CLOSE_ENOUGH_AUTO_APPLY_SAFE`, `CLOSE_ENOUGH_CURATED_PACKS_ENABLED`, `CLOSE_ENOUGH_RISK_INTERRUPT`, `CLOSE_ENOUGH_LOCAL_LEARNING_ENABLED`, `CLOSE_ENOUGH_UNDO_ENABLED`, and `CLOSE_ENOUGH_UNDO_TTL_SECONDS`; booleans must be `true` or `false`.

Curated packs are enabled by default; set `curated_packs_enabled` to `false` with `close-enough config set` to disable bundled and installed curated repairs for that configuration or session.

Undo is enabled for 30 seconds by default; set `undo_enabled` or `undo_ttl_seconds` with `close-enough config set`.

When an adapter displays `press Ctrl-G to undo` after a safe rewrite, Ctrl-G restores the original command buffer without submitting either command.

Session overrides affect only the invoking process and never modify configuration files.

Use `close-enough rule list|add|update|remove` to manage global exact-command exceptions; matching exceptions suppress diagnostics and never alter command execution.

Use `close-enough inspect-decision --command '<command>'` for full structured diagnostics and redaction-safe command diffs.

`close-enough doctor` includes remediation hints for shell adapter limitations.

Pack schema v1 is strictly compatible only with schema version `1`; legacy and future schemas are rejected without migration.

Pack and rule identifiers use lowercase kebab case; pack versions use SemVer 2.0.

Pack matchers are compiled as in-process regular expressions and never execute manifest text.

Transformation templates allow literal text, `$$`, and in-range `$1` capture references only. A matcher must cover the full command argument string; a safe rule never inherits unclassified trailing arguments.

Explanation templates use the same capture syntax and reject control characters.

Every pack rule must declare a risk class and static risk rationale.

Pack fixture schema v1 runs declarative command/input cases against expected rule IDs without executing manifest content.

Pack resolution sorts by pack ID and rejects duplicate IDs or duplicate command/pattern matchers.

Packs can declare a minimum engine SemVer and supported capability identifiers; validation rejects unmet or unknown requirements.

Bundled packs are embedded read-only and discovered deterministically at runtime.

Use `close-enough pack trust add <publisher> <base64-ed25519-public-key>` to explicitly enroll a publisher key obtained out of band. Use `close-enough pack install <pack.json> <signature>` to verify and atomically install an exact signed pack without overwrite.

Use `close-enough pack uninstall <id> <version>` to remove that exact managed pack file.

Pack signature verification uses detached Ed25519 signatures over exact pack bytes and is repeated when installed packs load. Installed packs are hint-only: they never rewrite or interrupt commands, even when their rules declare `safe` risk.

Project configuration requires `.close-enough/config.json` and a same-directory `trusted` marker owned by the current user; Unix markers must be `0600` and their directory must not be group- or world-writable.

History ranking and credential-backed history keys are not shipped features. The repository retains internal research abstractions only; close-enough does not create history keys, persist command history, or rank suggestions from history.

No self-update client or update channel is shipped. The update-manifest and bundled-pack archive helpers are internal release experiments and are not published as release assets.

Startup rejects privileged execution, relative or empty PATH entries, and group- or world-writable working directories; `close-enough doctor` reports these findings without blocking.

Secure writes and trusted project configuration require platform support for atomic replacement, restrictive permissions, and ownership verification; unsupported platforms fail closed.

Release builds report injected version and commit metadata through `close-enough version`.

Run the local CI target with `make ci`.

Run `make verify-local` for the Linux CI checks, latency gate, and Windows cross-compilation checks. It does not execute Windows runtime tests.

Install a version-pinned macOS or Linux release with `cosign` already on `PATH`. Verify the release-attached installer before executing it:

```sh
version=vX.Y.Z
base="https://github.com/gongahkia/close-enough/releases/download/$version"
curl -fsSLO "$base/install.sh"
curl -fsSLO "$base/install.sh.sigstore.json"
cosign verify-blob install.sh --bundle install.sh.sigstore.json \
  --certificate-identity "https://github.com/gongahkia/close-enough/.github/workflows/release.yml@refs/tags/$version" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
CLOSE_ENOUGH_VERSION="$version" sh install.sh
```

The verified installer downloads only the matching GitHub release archive, `checksums.txt`, and its Sigstore bundle; it verifies both the SHA-256 digest and the release-workflow identity before extracting. It adds one managed shell-init block for Zsh or Fish and removes legacy managed Bash blocks during upgrade. Run `CLOSE_ENOUGH_VERSION=vX.Y.Z sh install.sh --uninstall` to remove the binary and managed blocks; it does not install a background service.

On Windows PowerShell, verify the release-attached installer before running it:

```powershell
$version = 'vX.Y.Z'
$base = "https://github.com/gongahkia/close-enough/releases/download/$version"
Invoke-WebRequest "$base/install.ps1" -OutFile install.ps1
Invoke-WebRequest "$base/install.ps1.sigstore.json" -OutFile install.ps1.sigstore.json
cosign verify-blob install.ps1 --bundle install.ps1.sigstore.json `
  --certificate-identity "https://github.com/gongahkia/close-enough/.github/workflows/release.yml@refs/tags/$version" `
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Version $version
```

The PowerShell installer has the same archive-verification, initialization, and `-Uninstall` behavior.

Exit codes are stable: `0` success, `1` unexpected internal failure, `2` invalid CLI usage, `3` configuration failure, `4` invalid command or pack input, and `5` local operation failure.
