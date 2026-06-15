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
