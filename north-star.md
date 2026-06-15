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
- single-line installer: `curl -sSL shisa.sh/install | sh` (after auditing supply chain)

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
- **Phase 6 — Theming + starship importer.** Theme spec, gallery, `shisa import-starship`.
- **Phase 7 — 1.0 Launch.** Show HN post, brew formula, AUR, nixpkgs PR, blog series with benchmarks.
- **Phase 8 — Post-GA.** Plugin marketplace, community modules, optional local-LLM hint plugin (opt-in only).

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
