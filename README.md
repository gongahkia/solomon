# Solomon

<p align="center">
  <img src="./asset/logo/solomon.png" width="35%" alt="Solomon logo">
</p>

<h3 align="center">Local, deterministic terminal repair that explains before it changes a command.</h3>

<p align="center">
  <a href="#-start-with-solomon">Start</a> ·
  <a href="#-operate-it-carefully">Safety and privacy</a> ·
  <a href="./docs/distribution.md">Distribution</a> ·
  <a href="./CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <a href="https://github.com/gongahkia/solomon/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/gongahkia/solomon/ci.yml?branch=main&style=flat-square"></a>
  <img alt="Go 1.25+" src="https://img.shields.io/badge/go-1.25%2B-00ADD8?style=flat-square">
  <img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-green?style=flat-square">
</p>

Solomon diagnoses likely command mistakes before submission and after supported failures, then presents a risk-classified suggestion. It handles command, Git subcommand, and path typos, plus declarative semantic-repair packs. Its modes are hint, interrupt, rewrite, and off.

**Suggest, do not execute.** Solomon does not run a proposed repair. Its default is a non-blocking hint; an automatic rewrite is limited to bundled safe repairs, must be explicitly enabled, remains in the shell buffer until another Enter, and can be undone with Ctrl-G.

## Contents

- [🚀 Start with Solomon](#-start-with-solomon)
- [🤔 Why Solomon?](#-why-solomon)
- [🔎 How it works](#-how-it-works)
- [👀 Choose an entry point](#-choose-an-entry-point)
- [🧪 See it in action](#-see-it-in-action)
- [🛟 Operate it carefully](#-operate-it-carefully)
- [📚 Learn more](#-learn-more)
- [🌟 Contributing](#-contributing)

## 🚀 Start with Solomon

Solomon currently supports source installation with Go 1.25 or newer. From a clone of this repository:

~~~sh
go install ./cmd/solomon

# add $(go env GOPATH)/bin to PATH first if Go has not already done so
eval "$(solomon init --shell zsh)"

# make the Zsh integration persistent
solomon init --shell zsh >> ~/.zshrc

solomon check --format plain --command 'git sttaus'
~~~

New and migrated configurations use hint mode. For source installation, inspect adapter limitations with solomon doctor before adding an integration to a shell startup file.

There is no published release yet. Once a public versioned release exists, Go users can install it directly:

~~~sh
go install github.com/gongahkia/solomon/cmd/solomon@vX.Y.Z
~~~

## 🤔 Why Solomon?

Shell typos are routine, but command correction can also create risk: a suggestion can expose a secret, modify a filesystem, invoke elevated privileges, or affect a remote service. Solomon makes the diagnosis and its risk visible without silently replaying the command.

| When you need to… | Solomon helps by… |
| --- | --- |
| catch a likely typo before a command runs | inspecting bounded command input locally and returning a deterministic suggestion when it finds one |
| avoid automatic command replay | defaulting to a hint, and requiring explicit rewrite and auto_apply_safe opt-ins for the narrow safe-rewrite path |
| understand why a repair is constrained | reporting a static risk rationale without including raw command arguments in risk output |
| adapt common development commands | loading bundled declarative packs deterministically and validating their schema, risk metadata, and transformations |
| extend repair coverage carefully | requiring an explicitly trusted Ed25519 publisher key before an installed pack is accepted; installed packs remain hint-only |
| learn from recurring local corrections | keeping learning disabled by default and exposing reviewable drafts rather than automatically enabling a learned rule |

Solomon is a conservative shell-integrated assistant, not a command replay tool. It has no telemetry, remote inference, general shell-history persistence, or self-update client.

## 🔎 How it works

1. **Receive a shell event.** Zsh, Fish, and PowerShell adapters can ask the local daemon before submission and after a supported failure. Bash only emits non-blocking post-failure hints; it preserves PROMPT_COMMAND and does not install or change a DEBUG trap.
2. **Diagnose locally.** The engine uses bounded input, output, and analysis-time limits. It identifies missing commands from the local PATH, unknown Git subcommands, missing paths, and matching semantic-pack rules.
3. **Classify risk and choose an action.** Each decision is safe, unknown, or high. Configuration, shell capability, confidence, and rewrite eligibility determine whether the result is a hint, interrupt, rewrite, or no action.
4. **Keep rewrites reversible.** A safe bundled rewrite changes only the shell buffer, requires another Enter to run, and can be reverted through the daemon-issued Ctrl-G undo path within its configured lifetime.
5. **Keep optional state local.** The daemon maintains local session coordination. Optional learning records only qualifying failed/corrected pairs and produces a reviewable draft after three matching pairs.

## 👀 Choose an entry point

| Entry point | Best for | Start here |
| --- | --- | --- |
| Direct CLI | one-off, scriptable diagnostics | solomon check --format plain --command '<command>' |
| Structured inspection | automation or an accessible, detailed explanation | solomon inspect-decision --command '<command>' or solomon check --format json |
| Zsh integration | first-class pre-submission and post-failure assistance | solomon init --shell zsh |
| Fish or PowerShell integration | the same repair modes with adapter limitations reported by doctor | solomon init --shell fish or solomon init --shell powershell |
| Bash integration | non-blocking post-failure hints only | solomon init --shell bash |
| Pack management | trusted, declarative repair packs | solomon pack trust, solomon pack install, and solomon pack validate |

PowerShell requires PSReadLine. Plain diagnostics use color only on a terminal; pass check --color=never to disable it explicitly or --color=always to force it. Use check --format=plain --screen-reader for structured ANSI-free diagnostics without visual diff markers.

## 🧪 See it in action

Check a command directly:

~~~sh
solomon check --format plain --command 'git sttaus'
solomon inspect-decision --command 'git sttaus'
solomon doctor
~~~

Enable experimental failure-output capture for Bash or Zsh only:

~~~sh
eval "$(solomon init --shell zsh --experimental-output-capture)"
~~~

The experiment runs the shell through the platform script utility. Output passes through a private FIFO and is sanitized and redacted before Solomon retains at most 8 KiB for the current command; it does not write a transcript. Terminal programs can be affected. If the relay is unavailable, Solomon falls back to an exit-status-only hint.

Run the local project checks:

~~~sh
make ci
make latency-gate
make verify-local
~~~

make verify-local runs the Linux CI checks, the latency gate, and Windows cross-compilation checks; it does not run Windows runtime tests.

## 🛟 Operate it carefully

### Defaults, limits, and local privacy

Diagnosis runs locally and does not send command data over the network. Shell integrations do not write a general shell-history file or terminal transcript. Adapters display at most five hint or post-failure diagnostics in one loaded shell session and suppress duplicate suggestions; interrupt and rewrite safety behavior is not rate-limited.

Local learning is disabled by default. When local_learning_enabled=true, Solomon stores an owner-only SQLite database in $XDG_STATE_HOME/solomon or $HOME/.local/state/solomon. It records a failed/corrected pair only if its credential detector finds no secret in either command, and retains recognized-secret-redacted failure output capped at 8 KiB. Redaction is best effort, not a substitute for keeping credentials out of commands and terminal output.

Observations older than learning_retention_days are removed at daemon startup. The default retention is 30 days and the supported range is 1–90. After three matching pairs, learning produces a reviewable draft rather than enabling a rule. Use solomon learn list to inspect drafts and solomon learn purge --confirm=PURGE to remove learning data.

### Configuration and safety boundaries

Configuration is read from $XDG_CONFIG_HOME/solomon/config.json; an unset or relative XDG_CONFIG_HOME falls back to $HOME/.config/solomon/config.json. The only session overrides are SOLOMON_MODE, SOLOMON_AUTO_APPLY_SAFE, SOLOMON_CURATED_PACKS_ENABLED, SOLOMON_RISK_INTERRUPT, SOLOMON_LOCAL_LEARNING_ENABLED, SOLOMON_UNDO_ENABLED, and SOLOMON_UNDO_TTL_SECONDS. Session overrides affect only the invoking process and never change configuration files.

Use solomon rule list|add|update|remove for global exact-command exceptions. They suppress diagnostics and never alter execution. Project configuration requires .solomon/config.json plus a same-directory trusted marker owned by the current user; on Unix the marker must be 0600, and its directory must not be group- or world-writable.

Startup rejects privileged execution, relative or empty PATH entries, and group- or world-writable working directories. solomon doctor reports those findings without blocking. Secure writes and trusted project configuration require atomic replacement, restrictive permissions, and ownership verification; unsupported platforms fail closed.

### Repair packs

Pack schema v1 accepts only schema version 1; legacy and future schemas are rejected. Pack and rule identifiers use lowercase kebab case, pack versions use SemVer 2.0, and every rule declares a risk class and static rationale. Matchers are in-process regular expressions and never execute manifest text. Transformation and explanation templates accept only literal text, $$, and valid capture references; tail-preserving rules are never rewrite-eligible.

Bundled packs are embedded read-only and load deterministically. Curated packs are enabled by default; disable them with solomon config set curated_packs_enabled false. To install an external pack, explicitly obtain the publisher key out of band, then run:

~~~sh
solomon pack trust add <publisher> <base64-ed25519-public-key>
solomon pack install <pack.json> <signature>
~~~

Detached Ed25519 signatures cover the exact pack bytes and are verified again when installed packs load. Installed packs are hint-only even when a rule declares safe; use solomon pack uninstall <id> <version> to remove an exact managed pack.

### Releases and installers

The release workflow is configured to build signed macOS, Linux, and Windows archives, installers, checksums, SBOMs, and license-audit reports, but no public release has been published. Direct signed archives are the recommended path once one exists. Homebrew, WinGet, and AUR are not published; see the [distribution plan](./docs/distribution.md).

Release builds expose their injected version and commit through solomon version. When a versioned release is available, verify its release-attached installer with cosign before executing it. The installer verifies the matching archive checksum and Sigstore workflow identity, manages Zsh or Fish initialization on macOS/Linux (or PowerShell initialization on Windows), and supports uninstall. It does not install a background service.

## 📚 Learn more

- [Distribution plan](./docs/distribution.md)
- [Contributing guide](./CONTRIBUTING.md)
- [Security policy](./SECURITY.md)
- [Support guidance](./SUPPORT.md)
- [Code of conduct](./CODE_OF_CONDUCT.md)
- [Apache-2.0 license](./LICENSE) and [notice](./NOTICE)

## 🌟 Contributing

Contributions should preserve Solomon’s operating boundary: diagnose locally, explain the proposed repair, and leave execution to the user. Do not add automatic command replay, telemetry, remote inference, or a background service without an explicit design decision.

Before opening a pull request, run the relevant checks and add the narrowest regression test for the intended change. Repair packs are declarative data, not executable code: use stable identifiers, declare their risk and rationale, and include fixture coverage. See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full process.

## License

Solomon is available under the [Apache License 2.0](./LICENSE).
