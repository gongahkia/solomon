# Shisa — North Star

> A daemon-backed, async-first, cross-shell prompt that *never blocks*.
> Named for the Okinawan guardian (シーサー) placed at the gate — because the prompt is the gate to your shell.

---

## 1. One-line pitch

Shisa is a cross-shell prompt that runs as a background daemon, watches your filesystem, and pre-renders prompts so your shell is **never** slowed down by git status, language version probes, or cloud-context lookups — even inside `nixpkgs`, `chromium`, or a 10GB monorepo.

## 2. Why this exists

Starship is the de-facto cross-shell prompt today. It is excellent. It also has structural limitations that its maintainers have publicly declined to fix:

- **No async rendering.** Slow modules (git, language version probes) block the prompt. Users routinely set `command_timeout` to hide slowness rather than eliminate it.
- **No daemon / cache layer.** Every prompt re-spawns subprocesses and re-walks repo state. A [daemon concept gist](https://gist.github.com/nickwb/b12edea4152414bf5858c7b66f8171fe) was proposed years ago and never landed.
- **No instant prompt.** Powerlevel10k has it; starship does not. P10k is the only prompt with instant + transient + async, and its author has declared it on life support.
- **No transient prompt out of the box** for any shell.
- **Subshell overhead** in init scripts and module dispatch.

Tide solves these for fish-only. P10k solves these for zsh-only and is dying. Oh-my-posh is cross-shell but inherits the same per-render cost model as starship. **No project occupies the daemon-async + cross-shell + actively-maintained quadrant.** That is the opening Shisa takes.

## 3. Non-goals (so the scope stays honest)

- Shisa is **not** a shell. It does not replace zsh, bash, fish, nu, pwsh.
- Shisa is **not** a terminal emulator. It does not replace WezTerm, Alacritty, Ghostty, Warp.
- Shisa is **not** an AI coding agent. It does not write code, refactor, or run agents. (A future opt-in plugin may expose local-LLM hints; the core is AI-free.)
- Shisa is **not** a config compatibility layer. It will not be a drop-in for `starship.toml` at runtime. It ships a one-shot importer.

## 4. Differentiation matrix

| Feature                          | Starship | Powerlevel10k | Tide      | Oh-my-posh | **Shisa**       |
|----------------------------------|----------|---------------|-----------|------------|-----------------|
| Cross-shell (4+ shells)          | yes      | zsh only      | fish only | yes        | **yes**         |
| Background daemon                | no       | no            | no        | no         | **yes**         |
| Async git / language probes      | no       | yes           | yes       | no         | **yes**         |
| Instant prompt                   | no       | yes           | partial   | no         | **yes**         |
| Transient prompt (built-in)      | no       | yes           | yes       | partial    | **yes**         |
| fsnotify-based cache invalidation| no       | partial       | no        | no         | **yes**         |
| Pre-rendered prompts per cwd     | no       | no            | no        | no         | **yes**         |
| Sandboxed plugin scripting       | no       | no            | no        | partial    | **yes (Lua)**   |
| Actively maintained (2026)       | yes      | life support  | yes       | yes        | **yes**         |
| Zero telemetry                   | yes      | yes           | yes       | yes        | **yes**         |

## 5. Architectural pillars

### 5.1 Daemon-first
A single long-running per-user process (`shisad`) owns:
- filesystem watchers (FSEvents on macOS, inotify on Linux)
- a per-directory cache of git state, language tool versions, cloud context
- a render pipeline that produces *fully composed* prompt strings keyed by `(cwd, exit_code, jobs, cmd_duration)`

The shell-side hook is a ~5-line script that opens a Unix-domain socket, sends the four runtime values, and reads a pre-rendered string. Target round-trip: **< 2ms p99** on warm cache.

### 5.2 Async by default
Every module declares one of three execution classes:
- `sync`     — must complete before prompt prints (e.g., exit code coloring)
- `async`    — render placeholder, fill in on next prompt or via redraw escape
- `cached`   — read from cache; recompute only on fsnotify event

There is no `command_timeout`. There is no blocking I/O on the hot path.

### 5.3 Cache is the source of truth
Modules write to cache; the renderer reads from cache. The walker subsystem maintains cache freshness via filesystem events. Cold-start populates lazily on first cd into a directory; subsequent renders hit the cache.

### 5.4 Per-cwd memoization
Prompts are deterministic functions of `(cwd, exit_code, jobs, cmd_duration, cache_revision)`. The daemon keeps an LRU of fully-rendered prompts for the user's top-N most-visited directories. A `cd` to a memoized dir = string lookup.

### 5.5 Zig core, Lua plugins
- Daemon and renderer in **Zig** for cold-start, predictable allocations, and small binary size.
- Plugins authored in **Lua** (via embedded Lua 5.4 or LuaJIT) for ergonomics and a deep tradition in editor/window-manager plugin ecosystems (Neovim, WezTerm, Hammerspoon).
- Plugins run inside a capability-gated sandbox (see §8).

### 5.6 Clean-break config
TOML for declarative config (themes, module order, colors) + Lua for behavior (custom modules, conditional logic). A `shisa import-starship` command translates an existing `starship.toml` on a best-effort basis.

## 6. UX principles

1. **Speed is the feature.** Every design decision must defend p99 < 2ms warm render.
2. **Defaults are opinionated.** Out-of-the-box prompt is excellent; zero config required.
3. **Errors are loud.** Daemon down, socket missing, plugin crashed — surfaced inline, never silent.
4. **Transient by default.** History prompts shrink. Current prompt is full.
5. **No surprises.** Plugins declare what they do. No silent network calls. No background command exec.
6. **The shell is the boss.** Shisa never blocks shell input. If the daemon is unreachable, the fallback prompt prints in < 5ms.

## 7. Shell coverage

**v1.0 targets:** zsh, bash, fish, nushell, powershell.
**v1.x:** elvish, xonsh, ion, tcsh.

Each shell ships:
- an `init` snippet (eval'd from `.zshrc`/`.bashrc`/etc.)
- a precmd/preexec hook that sends runtime values to the daemon
- a redraw mechanism for async fill-in (zle in zsh, READLINE in bash, event-prompt in fish, etc.)

## 8. Security & plugin model

Two-tier plugin system:

**Tier 1 — Vetted core modules** (`shisa.modules.*`)
Built into the binary. Authored in Zig. Reviewed by maintainers. Full host access.

**Tier 2 — Third-party Lua plugins**
Loaded from `~/.config/shisa/plugins/`. Each plugin declares a manifest:

```lua
return {
  name = "kubectl-context",
  version = "0.1.0",
  capabilities = {
    fs_read = { "~/.kube/config" },
    fs_watch = { "~/.kube/config" },
    exec = false,
    net = false,
  },
  render = function(ctx) ... end,
}
```

The daemon enforces capabilities. A plugin that asks for `net = true` requires explicit user opt-in (`shisa plugin trust <name>`). The Lua VM runs with stripped stdlib (no `os.execute`, no `io.popen`, no `require` of arbitrary libs).

## 9. Platform coverage

**v1.0:** macOS (FSEvents), Linux (inotify). Windows users use WSL.
**v1.x:** native Windows via ReadDirectoryChangesW (community PRs welcome).

## 10. Performance targets (publicly benchmarked)

| Metric                            | Target          | How verified                  |
|-----------------------------------|-----------------|-------------------------------|
| Shell startup overhead            | < 5ms           | `hyperfine` against bare shell|
| Warm-cache prompt render          | < 2ms p99       | shisa bench, public CI        |
| Cold prompt in 10GB monorepo      | < 30ms          | nixpkgs / chromium benchmark  |
| Daemon RSS                        | < 25MB idle     | `ps`, public dashboard        |
| Daemon CPU idle                   | < 0.1%          | per-second sampling           |
| Async git in big repo (background)| < 200ms p99     | benchmark suite               |

A `shisa bench` subcommand runs the above locally and emits a shareable JSON report. No data leaves the user's machine.

## 11. Distribution

- `brew install shisa` (Homebrew core, eventually)
- `cargo binstall` for Rust users *(only after we ship a Rust-built fallback wrapper; primary build is Zig)*
- `scoop install shisa` (Windows via WSL)
- AUR (`shisa-bin`)
- nixpkgs
- repo installer script from GitHub Releases after supply-chain verification lands

## 12. Telemetry & privacy

**Zero telemetry.** Ever. No network calls in the daemon. The only network code path is `shisa update` (release check), opt-in.

Performance wins are surfaced through:
- The `shisa bench` CLI
- Public benchmarks in CI (vs. starship, oh-my-posh, p10k) on representative repos
- A `shisa report` command that produces a human-readable performance dump the user can paste into a bug report

## 13. License

**MIT.** Maximizes adoption, dotfile-shareability, and corporate friendliness. Mirrors the licensing of starship (ISC), p10k (MIT), oh-my-posh (MIT).

## 14. Roadmap phases (mapped to todo.md)

- **Phase 0 — Foundations.** Repo scaffolding, build system, RFC for the daemon protocol, name registration.
- **Phase 1 — Single-shell MVP.** Zsh + macOS only. Daemon, socket, sync modules (directory, exit, git basic). Proof: faster than starship on a cold render.
- **Phase 2 — Async core.** Async module class, redraw mechanism, transient prompt, fsnotify cache for git.
- **Phase 3 — Cross-shell parity.** Bash + fish. Instant prompt for zsh and fish.
- **Phase 4 — Plugin SDK + Lua sandbox.** Capability system, plugin loader, vetted-core module migration.
- **Phase 5 — Nu + PowerShell.** Wider shell support, Linux hardening.
- **Phase 6 — Theming + starship importer.** Theme spec, local preview, `shisa import-starship`.
- **Phase 7 — Distribution + supply chain.** Package channels, signing, SBOM/SLSA, installer, self-update verification.
- **Phase 8 — Deferred features.** Plugin marketplace, optional local-LLM hint plugin, advanced VCS integrations.

## 15. Success criteria

This project is successful (not just shipped) when:

- 5,000+ GitHub stars within 12 months of Phase 7.
- A reproducible benchmark suite shows ≥ 10× warm-render speedup over starship on `nixpkgs`.
- ≥ 50 community plugins published.
- Adoption is visible in dotfile repos (`github.com/search?q=shisa.toml`).
- The project has shipped a release on time every month for 6 consecutive months.

## 16. Risks (named honestly)

- **Zig is pre-1.0.** Language churn could cost weeks. Mitigation: pin to a Zig release, vendor stdlib slices we depend on.
- **Daemon lifecycle is hard.** Crashes, socket cleanup, multi-user systems, sandboxed environments. Mitigation: ship a robust supervisor + graceful fallback prompt.
- **Lua sandbox escape is a real attack surface.** Mitigation: stripped stdlib + capability gates + fuzz the bridge layer + bug bounty.
- **Starship has years of module breadth.** Catching up takes time. Mitigation: prioritize the top-20 most-used starship modules first; let community fill the long tail.
- **fsnotify gaps on macOS** (large dirs, recursive limits) and **inotify limits on Linux** (watcher count). Mitigation: opportunistic watching + periodic refresh fallback.
- **Cross-shell hooks are messy** (especially powershell + nu). Mitigation: keep the hook as small as possible; do real work in the daemon.

## 17. Open questions (to resolve before v0.1)

- IPC: unix socket only, or named pipe abstraction for future Windows-native?
- Cache backing: in-memory only, or memory-mapped sled-equivalent for cross-process resume?
- Theme spec: extend starship's preset format, or invent fresh?
- Wire protocol: line-delimited JSON vs. MessagePack vs. a hand-rolled framed binary?
- How does `shisa --no-daemon` behave? (degraded sync mode for restricted envs.)

---

# Extended Capabilities — Plugin Packs

Sections 1–17 above define the **core**. The core is opinionated, lean, perf-obsessed, and shippable on its own. Everything below is shipped as **official plugin packs** sitting on top of the same daemon, cache, and capability-gated Lua sandbox defined in §5.5–§8.

Three reasons this architecture matters:

1. **Each pack is opt-in.** A user who wants only "Starship but never blocks" never sees AI, cloud, or jj code paths.
2. **The packs are the differentiation moat.** Daemon-perf gets us baseline competitiveness with starship; the packs are what make Shisa land in users' dotfiles and stay.
3. **Pack scope is honest.** Each pack lists what it explicitly does **not** do, to prevent feature creep killing perf.

## 18. AI plugin pack (`shisa.ai`)

**Pitch:** the prompt that helps you finish the command you were about to type, without sending a byte to anyone's servers by default.

Local-first. Bundles a recommended small model recipe (`qwen2.5:1.5b`, `gemma3:1b`, or `phi3:mini` — final pick TBD by benchmark) via Ollama. Cloud providers (OpenAI, Anthropic, Gemini) require explicit `shisa plugin trust shisa.ai --net` and a key; the daemon enforces.

### Shipped modules

| Module                       | Trigger             | What it does                                                                 |
|------------------------------|---------------------|------------------------------------------------------------------------------|
| `nextcmd`                    | hotkey (e.g. Ctrl-O)| Suggests the next command given history + cwd + last output. Inline preview.|
| `nl2cmd`                     | type `?? <english>` | Converts natural language to a command. Always shows preview, never auto-runs.|
| `explain`                    | hotkey on a command | Plain-English breakdown of the command + every flag.                          |
| `risk`                       | pre-exec (Enter)    | Rules-engine first (fast, deterministic); SLM second (slow, optional).        |
| `errfix`                     | post non-zero exit  | Surfaces a `shisa: try `<x>`?` hint based on last stderr.                     |
| `histsearch`                 | hotkey (e.g. Ctrl-R)| Semantic search over shell history with local embeddings (atuin-style).       |
| `cdhint`                     | post-`cd` to new dir| Surfaces "looks like a Node project; common commands: ..." (rule-driven).    |

### Explicit non-goals
- **Not an agent.** Never runs commands without explicit confirmation. No autonomous loops.
- **Not Warp / Claude Code / Aider replacement.** Those are full coding agents; `shisa.ai` is prompt-line inline assist only.
- **Not a shell history replacement.** Optional integration with atuin via a thin adapter; does not import/sync atuin's DB.
- **Not a chat panel.** No conversation UI. Prompt-line and inline only.

### Privacy contract
- Default config: no network capability granted. The plugin literally cannot reach the internet.
- Cloud opt-in requires `shisa plugin trust shisa.ai --net=<provider>` per-provider, per-installation. Re-prompted on plugin upgrade.
- Every cloud request is logged locally (`~/.local/state/shisa/ai-requests.jsonl`) with redactable payload hashes for audit.
- A `shisa ai redact` rule file lets users define regex strings (`/sk-[A-Za-z0-9]+/`, `/AKIA[0-9A-Z]+/`) that are scrubbed before any provider call.

## 19. Cloud-safety plugin pack (`shisa.cloud`)

**Pitch:** stop nuking prod. The prompt screams when you're somewhere dangerous, and refuses to let you bypass it casually.

Cloud-safety is where the daemon's pre-exec hook pays for itself most obviously. Built atop the same Lua plugin model, but exposing extra integration points (pre-exec gate, multi-segment rendering, fsnotify on config files).

### Shipped modules

| Module                     | What it shows / does                                                                                       |
|----------------------------|------------------------------------------------------------------------------------------------------------|
| `cloud_ctx`                | Unified segment: AWS profile · GCP project · Azure subscription · k8s context+namespace. Daemon-cached.    |
| `risk_tier`                | Classifies the current cloud context as prod / staging / dev / unknown via regex + user rules. Colors the prompt's background bar.|
| `prod_guard`               | Pre-exec hook: when risk_tier=prod AND command matches a destructive pattern, demand typed confirmation.   |
| `iam_whoami`               | Current AWS/GCP/Azure principal/IAM user. Surfaces in detailed mode, hidden by default.                    |
| `sso_expiry`               | Reads cached SSO token expiry (AWS SSO, gcloud, az, Vault, 1Password CLI) and warns when < 30 min remain.  |
| `iac_workspace`            | Terraform / Pulumi / CDK workspace + lock state. Pre-exec warns if locked or drifted.                       |
| `region_drift`             | Warns when env `AWS_REGION` differs from profile-configured region. Same for `CLOUDSDK_CORE_PROJECT` etc.   |
| `cost_glance`              | Optional, hourly-refresh, cached month-to-date cloud spend. Heavy module; off by default; opt-in.          |
| `vpn_status`               | Detects active corp VPN (route table / wireguard / Tailscale / NetBird). Useful as a tier-gate.            |
| `ssh_target`               | When inside an active SSH session, displays the remote host with a risk-tier classification.                |
| `container_provenance`     | Inside docker / podman / devcontainer / nix-shell / distrobox / toolbx — show which one.                   |

### prod_guard contract

```
$ kubectl delete ns checkout
shisa: ⛔ this command targets a PROD-classified context (k8s://acme-prod).
       to proceed, type the tier name and press Enter:
> PROD
shisa: proceeding...
```

The guard's blocklist ships with sane defaults (`kubectl delete`, `kubectl drain`, `terraform destroy`, `aws ec2 terminate-instances`, `aws s3 rb`, `gcloud * delete`, `rm -rf`, `dd of=/dev/`, `mkfs`, `DROP TABLE`, etc.). Users extend via `~/.config/shisa/prod_guard.toml`. Shisa never *blocks* the command — it *gates* it. A user can always bypass with `--force` or by typing the tier name; the goal is breaking muscle memory, not adversarial defense.

### Explicit non-goals
- **Not a policy engine.** This is a habit-breaking UI layer, not OPA. Bypassable by design.
- **Not a cost dashboard.** `cost_glance` is a glance, not a finops tool. For real cost work, link out to AWS/GCP consoles or aws-finops-dashboard.
- **Not a credential manager.** `sso_expiry` reads cached state; it does not refresh, rotate, or store credentials.

## 20. VCS moat (`shisa.vcs`)

This is the section where Shisa builds a durable competitive moat. Starship's git module is the gold standard, but starship has no first-class support for jj, sapling, or hg, and patchy support for stacked-diff workflows. Shisa treats VCS plurality as a first-class concern.

### Shipped modules

| VCS                              | Status                          | Why it matters                                                                                              |
|----------------------------------|----------------------------------|-------------------------------------------------------------------------------------------------------------|
| Git                              | Tier 1                          | Universal. Async, cached, fsnotify.                                                                          |
| Jujutsu (jj)                     | Tier 1                          | 28k stars, fastest-growing alternative, Git-compatible. First-class support = mindshare.                     |
| Sapling (sl)                     | Tier 1                          | Meta's scalable VCS, OSS, used by Mercurial-flavor + smartlog teams.                                          |
| Mercurial (hg)                   | Tier 1                          | Still active at Facebook, Mozilla, large enterprise. Underserved by modern prompts.                          |
| Fossil                           | Tier 2 (community plugin)       | Small loyal base. Plugin-able rather than core.                                                              |
| Pijul                            | Tier 2 (community plugin)       | Niche.                                                                                                       |
| Bazaar / Breezy                  | Tier 2 (community plugin)       | Legacy.                                                                                                      |

### Stacked-diff awareness (`shisa.vcs.stack`)

Detects which stacking tool is in use and surfaces the stack:

| Tool                  | Detection                                                            |
|-----------------------|----------------------------------------------------------------------|
| Graphite (`gt`)       | `.graphite_repo_config` present                                       |
| ghstack               | Branch naming pattern + `.ghstackrc`                                  |
| spr / git-spr         | `.git/refs/spr/`                                                      |
| `st` (stack tool)     | `.git/st-meta` (or equivalent)                                        |
| git-spice (`gs`)      | `.git/spice-meta` (or equivalent)                                     |
| git-town              | `.git-town-branches.yml`                                              |
| Sapling stacks        | `sl smartlog` derivable                                               |
| GitHub native stacked PRs (`gh stack`) | Available as of 2026; detect via remote config        |

Shows the current position in the stack (e.g., `2/5 ↑↓`) so the user knows what they're on top of.

### Worktrees (`shisa.vcs.worktree`)

- Indicator: `wt:feature-x` when the cwd is inside a worktree
- Inventory: `shisa worktrees` lists all worktrees for the repo, marks the active one
- Multi-worktree safety: warn when two worktrees have uncommitted changes on related branches

### Explicit non-goals
- **Not a git CLI replacement.** Shisa is not lazygit, magit, or gh. It surfaces VCS state in the prompt and pre-exec hook.
- **Not a stack manager.** It doesn't push, restack, or restitch. It displays what your stacking tool already tracks.

## 21. Activity & focus pack (`shisa.activity`)

Small, well-defined pack covering the few non-stateful UX wins that don't fit elsewhere.

| Module               | What it does                                                                              |
|----------------------|-------------------------------------------------------------------------------------------|
| `long_running`       | When a foreground command has been running > N seconds, prompt shows a discreet timer.    |
| `cmd_complete_bell`  | Terminal bell / OSC-9 / desktop notification when a long command finishes.                 |
| `tmux_pane`          | When inside tmux, surface pane/window if helpful (configurable).                           |
| `right_prompt`       | Right-aligned secondary segment (time, battery, host) without consuming command space.    |

### Explicit non-goals
- Battery / cpu / network graphs (use bottom/btop).
- Notifications for arbitrary system events (use a notifier).

## 22. Plugin pack release strategy

Pack lifecycle:

1. **Incubation:** Pack lives in `incubator/<pack>` directory of main repo. Marked experimental. No stability guarantee.
2. **Graduation:** Pack is split into its own repo (`shisa-<pack>`), gets its own release cadence, and is published to the marketplace index.
3. **Vetted:** Pack is signed by maintainers and earns the `verified` badge in `shisa plugin list`.
4. **EOL:** Pack is moved to an archive list, kept installable, but new installs surface a warning.

Pack version is independent of core. Core declares `min_pack_api_version`. Packs declare `requires_core` semver range. Daemon refuses to load incompatible combos and prints a clear remediation.

## 23. Updated roadmap (extension; existing phases unchanged)

- **Phase 9 — Post-GA** (already defined; reused as continuous track).
- **Phase 10 — VCS moat pack (`shisa.vcs`).** Jujutsu first, then sapling, then hg. Stacked-diff awareness ships in 10.x.
- **Phase 11 — Cloud-safety pack (`shisa.cloud`).** Multi-cloud context + risk_tier + prod_guard first. Cost / drift / SSO last.
- **Phase 12 — AI pack (`shisa.ai`).** Local Ollama integration. Ship `nextcmd`, `nl2cmd`, `risk`, `explain`, `errfix` in order of user value.
- **Phase 13 — Activity & focus pack (`shisa.activity`).** Smaller. Slot in opportunistically.
- **Phase 14 — Plugin marketplace polish.** Verified badges, signed manifests, installable from `shisa plugin install <name>`.

These phases run in parallel to continuous core hardening. Pack work must not regress core perf targets.

## 24. Honest scope opinions

The following ideas surfaced during research and are **explicitly rejected** for v1 to keep the project shippable. Each is rejected with a reason, not because it's bad, but because it's a different product:

- **Full AI agent / autonomous mode.** This is Claude Code / Aider / Goose / OpenCode territory. Shisa stays inline + opt-in.
- **Terminal emulator.** This is WezTerm / Alacritty / Ghostty / Warp / Wave territory.
- **Replacing the shell.** Nu, fish, Brush, Ion already exist.
- **Cloud cost dashboard.** aws-finops-dashboard already serves this need. `cost_glance` is a *glance*, not a dashboard.
- **MCP server.** Shisa is a prompt, not an agent gateway. If users want their AI agent to read shell history, atuin/suvadu/engram-mcp do that.
- **Built-in remote sync of configs.** Dotfile sync is a solved problem (chezmoi, stow, yadm). Shisa stays local-first.
- **GUI configurator.** A `p10k configure` style wizard is tempting, but a TOML + Lua starting template + a `shisa init --interactive` CLI cover the same UX without GUI scope.

## 25. Success criteria (extended)

In addition to §15:

- The VCS moat must be visible: ≥ 1 viral blog post comparing Shisa's jj/sapling/hg support to starship's, within 6 months of Phase 10.
- The cloud-safety pack must surface at least 3 documented "Shisa saved my prod" anecdotes from real users within 12 months of Phase 11.
- The AI pack must run end-to-end on a 2020-era MacBook Air with a 1.5B-parameter model in under 800ms latency for `nextcmd`.

---

# Implementation Specifications

Sections 26+ are concrete specs that pin down what the abstractions in §5–§22 actually look like. These are normative for v1.0; sub-revisions of the spec are tracked in `rfcs/`.

## 26. Wire protocol specification

### 26.1 Framing

Length-prefixed JSON over `SOCK_STREAM` Unix-domain socket:

```
+-----------+----------------------------+
| u32 BE    | UTF-8 JSON payload, len-N  |
+-----------+----------------------------+
```

- Max payload: 1 MiB (rejected with `E_OVERSIZE` over the same frame format).
- One request per frame; one response per frame.
- No keep-alive multiplexing in v1 (defer to v2). Connection-per-request keeps the model trivial.

### 26.2 Request schema

```json
{
  "v": 1,
  "op": "render",
  "shell": "zsh|bash|fish|nu|pwsh",
  "cwd": "/abs/path",
  "exit": 0,
  "jobs": 0,
  "duration_ms": 1234,
  "cols": 200,
  "rows": 50,
  "tty": "/dev/ttys001",
  "color_caps": "truecolor|256|16|none",
  "glyph_caps": "nerdfont|unicode|ascii",
  "user_id": 501,
  "session": "uuid-v4",
  "request_id": "uuid-v4"
}
```

Other ops (v1): `health`, `metrics`, `reload`, `version`, `subscribe` (editor integration; see §34).

### 26.3 Response schema

```json
{
  "v": 1,
  "request_id": "uuid-v4",
  "prompt": "ANSI-encoded string",
  "redraw_token": "opt-string",
  "trailer": null,
  "diagnostics": [],
  "elapsed_us": 1234
}
```

`redraw_token` is non-null when async modules are still pending. The shell echoes the token back on a `render_continue` op to receive an updated prompt without re-sending state.

### 26.4 Versioning

- The `v` field is required on every frame.
- Daemon refuses `v` it doesn't understand and replies with `E_VERSION` plus the highest version it speaks.
- The shell hook script is responsible for downgrading or upgrading the request shape.
- Wire protocol changes go through an RFC and follow semver: `v.major` breaks; `v.minor` adds fields (clients ignore unknown).

### 26.5 Error envelope

```json
{
  "v": 1,
  "request_id": "uuid-v4",
  "error": { "code": "E_VERSION", "message": "...", "context": {...} }
}
```

Error codes are an explicit enum, documented in `docs/protocol/errors.md`.

### 26.6 Hot-path budget

End-to-end p99 budget for a `render` op on warm cache: 2ms. Allocations: zero on the hot path. The daemon owns pre-allocated arenas keyed by `session`. Profile assertions in tests.

## 27. Lua plugin API surface

### 27.1 Plugin manifest (`plugin.lua`)

```lua
return {
  name = "kubectl-context",
  version = "0.2.1",
  api_version = "1",
  description = "kube context + ns segment",
  author = "alice <alice@example.com>",
  license = "MIT",
  capabilities = {
    fs_read   = { "~/.kube/config", "~/.kube/cache/" },
    fs_watch  = { "~/.kube/config" },
    exec      = false,
    net       = false,
    secrets   = false,
    env_read  = { "KUBECONFIG" },
    pre_exec  = false,
  },
  modules = { "k8s_ctx" },
}
```

### 27.2 Module entry contract

```lua
function k8s_ctx.render(ctx)
  -- ctx is read-only proxy. Methods: ctx:cwd(), ctx:env(name), ctx:read(path),
  -- ctx:fs_event_for(path), ctx:cache_get(key), ctx:cache_put(key, value, ttl_ms)
  return {
    text     = "k8s://acme-prod/payments",
    style    = { fg = "red", bold = true },
    risk     = "prod",          -- contributes to risk_tier aggregation
    glyph    = "\u{e75e}",      -- with ASCII fallback
    a11y     = "Kubernetes context acme-prod namespace payments",
  }
end
```

### 27.3 Module lifecycle

- `on_load(ctx)` — once, after the plugin is loaded; may register fs watchers
- `render(ctx)` — called per prompt; **must be <1ms or be declared async**
- `update(ctx, event)` — called on watcher events; updates cache
- `pre_exec(ctx, command)` — optional; may return `{ ok = false, prompt_for_confirm = "..." }`
- `on_unload(ctx)` — cleanup

### 27.4 Sandbox rules

- Stripped Lua stdlib: removed are `os.execute`, `os.exit`, `os.remove`, `os.rename`, `io.popen`, `io.open` (whitelisted via `ctx:read`), `loadfile`, `dofile`, `require` (whitelisted to project-local files), `package.loadlib`, `debug.*` (most).
- Allowed: pure-Lua `string`, `table`, `math`, `utf8`, restricted `os` (time only).
- Memory limit per plugin: 16 MiB hard cap, instrumented allocator. Plugins above cap are killed and logged.
- CPU budget per `render`: 1 ms wall (hard kill after 5 ms in debug, fail-fast).

### 27.5 Capability gates

Capabilities are declared in the manifest and enforced by the daemon. Re-prompting required on upgrade if the requested capability set changes. The daemon refuses to load plugins with undeclared capability usage at runtime.

A plugin trying to use `ctx:exec()` without the `exec` capability errors immediately and is logged.

### 27.6 Stable API guarantees

- `ctx.api_version` is semver. Plugins declare `api_version` they target; daemon supports the last two majors.
- New functions in the `ctx` namespace ship as `api_version`-additive; never break compatibility within a major.

## 28. Theme & rendering spec

### 28.1 Color model

Internal color model uses Oklab (perceptually uniform) for interpolation. Output is downcast to terminal capability:

- truecolor → 24-bit RGB
- 256 → ANSI 256 palette (nearest in Oklab)
- 16 → ANSI 16
- none → no color, glyph-only

### 28.2 Theme file

```toml
[meta]
name = "okiya-night"
author = "shisa-core"
version = "1.0.0"
contrast_min = 4.5            # WCAG AA enforced at theme-validate time
license = "MIT-0"

[palette]
fg       = "oklch(0.95 0.02 200)"
bg       = "oklch(0.18 0.02 200)"
accent   = "oklch(0.75 0.15 150)"
warn     = "oklch(0.80 0.20 90)"
danger   = "oklch(0.65 0.25 30)"

[modules.cwd]
fg = "@accent"
bold = true

[modules.risk_tier]
prod    = { bg = "@danger",  fg = "white", bold = true, glyph = "" }
staging = { bg = "@warn",    fg = "black" }
dev     = { fg = "@accent" }
```

### 28.3 Theme validator (`shisa theme validate`)

Run before publish:
- All semantic pairs (`fg/bg`) meet `contrast_min`.
- All glyphs have an ASCII fallback declared.
- Theme works on 16-color, 256-color, truecolor.
- A11y mode rendering tested.

### 28.4 Glyph fallback

```toml
[glyphs]
git     = { nerdfont = "", unicode = "⎇", ascii = "git" }
prod    = { nerdfont = "", unicode = "⚠",  ascii = "!!" }
```

Daemon picks the right tier from `glyph_caps`. Themes declaring `nerdfont` glyphs must also declare unicode + ascii fallbacks; validator enforces.

### 28.5 Multi-line layout

Themes can declare segment arrangement:

```toml
[layout]
lines = [
  ["risk_tier", "cloud_ctx", "vcs", "%filler%", "right_segments"],
  ["cwd"],
  ["prompt_char"],
]
right_segments = ["cmd_duration", "time"]
```

Filler is a single expanding-width spacer per line.

## 29. Daemon lifecycle & supervisor

### 29.1 Process model

- One `shisad` per user (enforced by `flock` on the socket path lock file).
- Optional `shisa-supervisor` lightweight watchdog (~200 KiB binary) that restarts `shisad` on crash with exponential backoff.
- The shell hook never connects to the supervisor; it always connects to the socket.

### 29.2 Auto-spawn

If `shisa prompt` finds no daemon, it forks `shisad` itself with `--auto-spawn`, waits up to 100 ms for the socket, falls back to a sync renderer if not ready in time.

### 29.3 Graceful shutdown

- `SIGTERM`: drain in-flight requests (5 s deadline), unlink socket, exit 0.
- `SIGINT`: same.
- `SIGUSR1`: reload config.
- `SIGUSR2`: dump goroutine-equivalent stack to log.

### 29.4 Health checks

- `shisad --health` → exits 0 if reachable.
- `shisad --metrics` → JSON dump of cache stats, render histogram, plugin status.
- Heartbeat between shisad and supervisor every 1 s.

### 29.5 Multi-user / multi-host

- Per-user socket: never shared across users.
- SSH'd-in sessions get their own daemon on the remote host (auto-spawn applies).
- sudo: `sudo shisa prompt` opens to root's daemon, not the original user's. Document this surprise.

## 30. Cache architecture

### 30.1 Layers

- **L1: rendered-prompt LRU**, keyed by `(cwd, exit, jobs, duration_bucket, cache_rev)`. Capacity: 1024 entries. Pure in-memory.
- **L2: module-output cache**, keyed by `(plugin_id, scope)`. Persisted optionally to `~/.cache/shisa/cache.bin` for cold-start hydration.
- **L3: external-command cache**, keyed by `(cmd, args, cwd)`. Invalidated by fsnotify on declared paths.

### 30.2 Invalidation

- File event → invalidate all entries whose `fs_watch` declarations match.
- Time-based: each module declares `max_age_ms`; expired entries refresh on next render.
- Manual: `shisa cache clear [--module=foo]`.

### 30.3 Cache revision

A monotonic `cache_rev` is incremented on every invalidation. L1 keys include `cache_rev` so eviction is automatic.

## 31. Async / redraw mechanism per shell

### 31.1 Zsh

- Implemented via `zle reset-prompt` triggered by a self-pipe FD that the daemon writes to once an async module fills.
- Hook script keeps an FD open per session.

### 31.2 Bash

- `bind -x` plus a custom escape sequence (`\e]9000\a`) the daemon emits; the binding re-invokes the prompt.
- Document Bash 4+ requirement; older shells get a graceful-degraded sync prompt.

### 31.3 Fish

- Native `prompt_pwd` + `fish_prompt` + `commandline -f repaint`.
- Async via `fish-async-prompt` mechanism without bringing in that library.

### 31.4 Nushell

- `PROMPT_COMMAND` returns initial. A second prompt eval fires on async-fill via a custom `nu` event hook.

### 31.5 PowerShell

- `prompt` function + `Register-EngineEvent` for async-fill, where supported. Documented degradation list.

## 32. Security threat model

STRIDE-flavored survey of the surface area:

| Category    | Concrete threat                              | Mitigation                                                                 |
|-------------|----------------------------------------------|----------------------------------------------------------------------------|
| Spoofing    | Other user attaches to my daemon socket      | Socket in `$XDG_RUNTIME_DIR` (Linux) / user Library cache (macOS), 0700.   |
| Spoofing    | Malicious plugin impersonates a vetted one   | Marketplace requires signed manifests; daemon checks signature on install. |
| Tampering   | Plugin modifies host process state           | Sandbox; capability gates; stripped Lua stdlib.                            |
| Repudiation | "I didn't run that destructive command"      | prod_guard audit log; opt-in shisa.history adapter.                        |
| Info disc.  | Plugin reads `.env`, sends to attacker       | `net` capability gated; `fs_read` scoped; redaction rules.                 |
| Info disc.  | AI plugin sends prompt to cloud provider     | `net` gated; per-provider opt-in; redaction rules; local-only default.     |
| DoS         | Plugin infinite-loops in `render`            | 1 ms wall budget, 5 ms hard kill, plugin disabled after 3 strikes.          |
| Elev. priv. | Lua sandbox escape via FFI / metatable abuse | Stripped stdlib; fuzz bridge; bug bounty; quick-pull mechanism.            |
| Supply chain| Daemon binary tampered                       | Sigstore signing, SBOM published, SLSA Level 2 attestation, repro builds.   |

Security-sensitive changes update the local capability, signing, and protocol docs that describe the affected surface.

## 33. Accessibility commitment (WCAG AA + a11y mode)

### 33.1 Baseline

- All built-in themes pass 4.5:1 contrast for text and 3:1 for UI signals.
- Every color-encoded signal also has a glyph and a text alternative.
- The `risk_tier=prod` segment is bold, glyph-marked, and tagged in `a11y` strings — not color-only.

### 33.2 `--a11y` mode

```
$ shisa init --a11y
```

- Strips all colors; uses ASCII glyphs and labels.
- Adds explicit text labels (`[prod]`, `[git: main *]`, `[aws: acme-prod]`).
- Disables NerdFont glyph requirement.
- Compatible with screen-reader-friendly terminals (Mac VoiceOver, NVDA-piped terminals).

### 33.3 Screen-reader integration

- The prompt emits OSC-7 (current directory) and a custom OSC-1337-style `a11y-summary` sequence on a11y mode, summarizing context in one line for screen readers.
- Optional `shisa.a11y.live` plugin announces risk-tier transitions via terminal bell or DBus notification.

### 33.4 Contrast CI

- All themes run through a contrast checker on every PR.
- New themes refused until pass.
- Local theme preview output shows contrast validation results.

### 33.5 Keyboard-only operation

- All Shisa CLI subcommands are non-interactive by default (use `--interactive` to opt into TUIs).
- Interactive wizards are TTY-tolerant; no graphical popups.

## 34. Editor integration spec

### 34.1 Why

Editors with statuslines (Helix, Neovim, Zed) re-implement git, cloud, k8s context. Shisa already has all this state computed and cached. Expose it.

### 34.2 `subscribe` op

```json
{ "v":1, "op":"subscribe", "topics":["vcs", "cloud_ctx", "risk_tier"], "cwd":"/abs" }
```

The daemon streams snapshot + incremental updates (NDJSON) until the socket closes. No polling cost.

### 34.3 Read-only

The subscribe endpoint is strictly read-only. No editor can mutate Shisa state; this prevents an editor extension being used to bypass `prod_guard`.

### 34.4 Bridges

- `contrib/editor-bridges/helix-shisa.toml` — statusline integration
- `contrib/editor-bridges/shisa.nvim` — small Lua plugin for Neovim
- `contrib/editor-bridges/shisa-zed` — extension shipped via Zed's marketplace

Each bridge stays minimal: connect, subscribe, render. No business logic.

### 34.5 Auth & privacy

Editors only see the data the user's terminal already sees. No new privacy surface. Editor bridges declare which topics they subscribe to in their own config.

## 35. Governance & Vouch

### 35.1 Model

BDFL-start with explicit transition triggers. The transition is *committed in writing* before launch so it isn't theoretical.

### 35.2 Triggers

- 5 active contributors (≥ 10 merged PRs each over 12 months) → form a 3-person Steering Group via PEP-13 style vote.
- 1,000 GitHub stars + 100 plugin authors → spin up the marketplace stewardship sub-team.
- Either trigger met → bring on a co-maintainer with full commit rights.

### 35.3 Commit access via Vouch

Shisa adopts [Vouch](https://news.lavx.hu/article/mitchell-hashimoto-launches-vouch-explicit-trust-management-for-open-source-communities) (Mitchell Hashimoto's trust-management system, designed to combat AI-slop PRs).

- New contributors start at unvouched. Their PRs are still welcome but require review by ≥ 2 vouched contributors.
- Vouching is granted only by those with write access; vouched users cannot themselves vouch.
- Vouch state is tracked in `VOUCHES` (POSIX-parseable text file) at the repo root.
- A `shisa vouch verify` CLI subcommand validates the file's structure.

### 35.4 RFC process

- All proposals affecting wire protocol, plugin API, security, or theme spec require an RFC in `rfcs/`.
- Numbered, dated, owned, with explicit "rejected alternatives" and "non-goals" sections.
- 14-day public comment window minimum.
- Lazy consensus: silence is acceptance after comment window.
- BDFL can override RFC consensus with a written reason in the merge commit; rare, public.

### 35.5 Code of conduct

Contributor Covenant 2.1. Enforcement via maintainer team; escalations via project email. Bans are public; appeals tracked in a private repo.

## 36. Funding & sustainability

### 36.1 Stance

Shisa is OSS-free-forever. No paid tier. No private plugins. No cloud lock-in.

### 36.2 Funding sources

Community funding is out of current scope.

### 36.4 No selling out

Shisa will never relicense to a more restrictive license. The MIT decision is final.

## 37. Project voice

- Calm, technical, opinionated.
- Never breathless. Never AI-style "delve" or "underscore".
- Never makes claims it can't benchmark.

### 37.3 Visual tokens

- Primary palette: warm dark grays + a single accent (`#FF6E50`-ish coral).
- Typography: a humanist sans for prose, JetBrains Mono for code samples.
- README remains the canonical public overview.

### 37.4 Public surface

- README and GitHub Releases are canonical.

## 38. Documentation strategy

### 38.1 Tiers

- **Quickstart:** README install + 5 min to a working prompt.
- **Recipes:** task-driven, copy-paste-runnable.
- **Reference:** generated from sources (config schema, CLI, plugin API).
- **Internals:** the architecture, threat model, RFCs, profiling notes.

### 38.2 Tooling

- Schema docs auto-generated from `build.zig` + a `shisa schema dump`.
- Examples folder is CI-tested.
- All docs run through `vale` for style consistency.

## 39. Testing strategy & quality gates

### 39.1 Layers

| Layer            | What                                                   | Where                                   |
|------------------|--------------------------------------------------------|-----------------------------------------|
| Unit             | Zig source-level                                       | `zig build test`                        |
| Property         | Wire protocol roundtrip, theme rendering invariants    | `zig build test-prop`                   |
| Snapshot         | Prompt outputs against fixtures                        | `tests/snapshots/`                      |
| Fuzz             | Protocol decoder, Lua bridge, redaction rules          | `zig build fuzz` + nightly OSS-Fuzz     |
| Integration      | Real shell sessions via `expect`/`pexpect`             | `tests/shells/`                         |
| End-to-end       | Dockerized full-OS runs                                | `tests/e2e/`                            |
| Benchmark        | hyperfine + microbench + memory                        | `zig build bench`                       |
| Contract         | Plugin API compatibility on min/max api_version        | `zig build test-contract`               |
| Accessibility    | Contrast ratios, screen-reader plumbing                | `zig build test-a11y`                   |

### 39.2 Quality gates

- Every PR: unit, property, snapshot, contract, accessibility.
- Tagged release: also fuzz (1-hour CI), full integration, e2e, benchmark.
- Benchmark regression > 10% on warm render → PR blocked.

### 39.3 Test environments

- macOS-14, macOS-15 (CI)
- Ubuntu-22.04, Ubuntu-24.04, Arch-rolling, Fedora-40 (CI)
- WSL2 on Windows-11 (CI)
- Real-hardware perf bench monthly on a documented baseline machine

## 40. Release engineering + supply chain

### 40.1 Versioning

Semver. `v0.x` is API-unstable; `v1.0` is the first stable wire protocol + plugin API.

### 40.2 Release cadence

- Monthly minor releases, first Tuesday of each month.
- Patch releases as needed (security: within 72 hours of fix).
- Quarterly stability summaries.

### 40.3 Supply-chain

- Reproducible builds (deterministic `zig build` with locked dependencies).
- SBOM generated per release (SPDX format).
- Sigstore cosign keyless signing for every artifact.
- SLSA Level 2 attestation in CI (verifiable provenance).
- Public release-checksum file signed.
- `shisa update --verify` checks signatures before applying.

### 40.4 Distribution channels

- GitHub Releases (primary)
- `brew install shisa` (Homebrew tap → core)
- `aur/shisa-bin` and `aur/shisa-git`
- Nixpkgs derivation
- `scoop install shisa` (WSL)
- `cargo binstall` shim (post-v1)
- AppImage for portable Linux
- Flatpak (community)
- Snap (community)
- DEB + RPM packages
- repo installer script with signature verification

### 40.5 Deprecation policy

- One major version of overlap when removing a deprecated API.
- Deprecation announced in release notes + `shisa doctor` warnings.
- Migration tooling shipped before removal.

## 41. Internationalization

### 41.1 Glyphs vs translations

- Glyphs are universal (NerdFont + Unicode).
- User-facing strings (errors, CLI help, doctor messages) are translatable.
- Prompt segments are user-configured templates; no translation of user text.

### 41.2 Locale support

- gettext-style message catalogs in `i18n/`.
- Initial: en-US. Translations welcomed via PR.
- Locale selected by `LANG` / `LC_*` env or `shisa config set locale=...`.

### 41.3 Right-to-left rendering

- Detect RTL locale and reverse segment order in the prompt when configured.
- Tested with Arabic, Hebrew, Persian fixture strings.

### 41.4 CJK width handling

- East Asian Width (UAX-11) compliance in segment widths.
- Tested with Chinese / Japanese / Korean fixture strings.

## 42. Migration tooling (expanded)

Beyond `import-starship` (§7 / Phase 7):

- `shisa import-p10k` — translates Powerlevel10k config (zsh-only source).
- `shisa import-oh-my-posh` — translates oh-my-posh JSON themes.
- `shisa import-tide` — translates tide settings (fish-only source).
- `shisa import-pure` — minimalist baseline.
- All importers emit a `migration-notes.md` next to the new config listing what couldn't be translated.

## 43. Glyph & font compatibility

### 43.1 Tiers

- `nerdfont`: full NerdFont set.
- `unicode`: standard Unicode symbols.
- `ascii`: alphanumerics + punctuation only.

### 43.2 Detection

- The shell hook reports `glyph_caps` heuristically (e.g. `TERM_PROGRAM`, `LANG`, env hints).
- Override via `shisa config set glyph_caps=ascii`.
- `shisa font check` runs a font-rendering probe and recommends settings.

### 43.3 NerdFont version pinning

- Themes declare minimum NerdFont version they require.
- Themes using post-v3.0 codepoints are flagged at install.
- Symbols-Only variant supported as fallback for users keeping their preferred base font.

## 44. Advanced VCS states (git-focused, mirrors for jj/sapling/hg)

The `git` module surfaces:

- Clean / dirty / staged / unstaged / untracked counts
- Active operation: rebase / merge / cherry-pick / revert / bisect / am
- Detached HEAD state
- Sparse-checkout active (with cone vs non-cone)
- LFS active + pointer-only state
- Submodule states (dirty, behind, ahead)
- Worktree (which one)
- Branch ahead/behind upstream
- Conflict file count
- Stash count
- Last fetch age (warns if > N hours stale)
- HEAD's signed-commit state (gpg/ssh signed?)

Each state has an inline glyph + ASCII fallback + a11y label. Jujutsu / Sapling / Mercurial mirror this surface to their native concepts.

## 45. v2 roadmap (post-1.0)

- **Native Windows support** (ReadDirectoryChangesW, PowerShell hook polish).
- **Persistent daemon across reboots** (system service install).
- **Encrypted, opt-in dotfile sync** via age + git remote (no Shisa server involved).
- **Per-project Shisa config layering** (`./shisa.toml` overrides) with secure precedence rules.
- **Plugin marketplace 2.0** (search, ratings, audit reports).
- **Mobile (Termux, iSH) basic support** if community asks for it.
- **Web preview** (`shisa web preview <config>`) for sharing prompt designs.
- **MCP-bridge plugin** (separate repo) for power users who want their AI agent to consult Shisa's cached cloud / VCS state.

These are scoped intentionally loose. The v2 RFC opens 30 days after v1.0 ships.

## 46. Failure modes & graceful degradation

| Failure                                  | Behavior                                                    |
|------------------------------------------|-------------------------------------------------------------|
| Daemon socket missing                    | Auto-spawn daemon; fallback to sync prompt in < 5 ms.        |
| Daemon panics                            | Supervisor restarts with backoff; user prompt unaffected.    |
| Plugin renders > 5 ms                    | Plugin disabled for the session; warning in `shisa doctor`. |
| Plugin uses undeclared capability        | Plugin disabled; loud error.                                |
| Lua sandbox detects escape attempt       | Plugin quarantined; user notified.                          |
| fsnotify watcher limit exceeded (Linux)  | Fall back to periodic refresh; advise raising the limit.    |
| Out-of-disk for cache                    | LRU eviction; cache size reduced; warned in doctor.         |
| Network unreachable (cloud-AI plugin)    | Plugin returns inline error; never blocks the prompt.       |
| Tampered binary                          | `shisa update --verify` fails closed.                       |
| User's terminal lacks truecolor          | Theme downgrades automatically.                             |
| User's terminal lacks NerdFont           | Glyphs downgrade to Unicode or ASCII automatically.          |
| Shell version too old                    | `init` script emits a one-line warning; minimal sync mode.   |
| Sudo'd shell session                     | Documented behavior: connects to root's daemon, not user's.  |
