# Shisa — Task Breakdown

Each line is one discrete unit of work. Phases map to `north-star.md` §14.
Status legend: `[ ]` open  `[~]` in progress  `[x]` done.

---

## Phase 0 — Foundations

- [ ] Reserve `shisa` org/handle on GitHub
- [ ] Reserve `shisa-prompt` crate name as a placeholder (in case we ever ship Rust wrappers)
- [ ] Reserve `shisa.sh` domain for landing + install script
- [ ] Reserve `@shisa` on npm in case of node-side install tooling
- [ ] Decide canonical README/landing copy + the one-line pitch
- [ ] Author `LICENSE` (MIT) at repo root
- [ ] Author `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)
- [ ] Author `CONTRIBUTING.md` (build, test, RFC process)
- [ ] Author `SECURITY.md` (responsible disclosure address, scope)
- [ ] Set up `.editorconfig`, `.gitattributes`
- [ ] Choose Zig toolchain version and pin in `build.zig.zon`
- [ ] Initialize `build.zig` skeleton (debug + release + benchmark steps)
- [ ] Set up GitHub Actions matrix: macOS-14, ubuntu-22.04, ubuntu-24.04
- [ ] Configure release-please / cargo-dist equivalent for Zig (manual tag-driven release for v0)
- [ ] Set up sccache-equivalent caching for Zig builds in CI
- [ ] Write RFC-0001: Daemon wire protocol (framing, message types, versioning)
- [ ] Write RFC-0002: Module execution classes (sync, async, cached)
- [ ] Write RFC-0003: Lua plugin capability manifest schema
- [ ] Write RFC-0004: Cache invalidation rules (per-module fsnotify scope)
- [ ] Set up `rfcs/` directory and a template
- [ ] Set up issue templates (bug, perf regression, plugin request, RFC)
- [ ] Set up PR template (checklist: tests, benchmarks-run, RFC-referenced)
- [ ] Create project board with milestones aligned to phases
- [ ] Stand up minimal landing page on `shisa.sh` (single HTML, install one-liner, link to repo)
- [ ] Write the architecture overview doc (`docs/architecture.md`)
- [ ] Pick the wire protocol (line-delimited JSON for v0, swap to binary if benchmarks demand)
- [ ] Decide socket path convention (`$XDG_RUNTIME_DIR/shisa.sock` on Linux, `~/Library/Caches/shisa/shisa.sock` on macOS)

## Phase 1 — Single-shell MVP (zsh on macOS)

### 1.1 Daemon skeleton
- [ ] `shisad` entry: parse CLI args, daemonize with `posix_spawn` or fork+setsid
- [ ] Implement single-instance lock via flock on the socket path
- [ ] Implement unix-domain socket server (accept loop, per-conn handler)
- [ ] Implement graceful shutdown on SIGTERM/SIGINT (drain in-flight requests, unlink socket)
- [ ] Implement crash-restart supervisor (separate `shisa supervisor` binary or `--supervise` flag)
- [ ] Implement structured logging to `~/Library/Logs/shisa/shisad.log`
- [ ] Implement log rotation (size-based, 5×10MB ring)
- [ ] Implement `shisad --version`, `--health`, `--metrics` admin endpoints

### 1.2 Wire protocol v0
- [ ] Define request frame (length-prefixed JSON): `{cwd, exit, jobs, duration, shell, cols, rows}`
- [ ] Define response frame: `{prompt, redraw_token?}`
- [ ] Implement encoder/decoder in Zig with fuzz tests
- [ ] Implement client library (`shisa-client.zig`) for use by `shisa prompt`
- [ ] Implement `shisa prompt` CLI that connects to daemon and prints

### 1.3 Sync modules (v0)
- [ ] `cwd` module: display current directory with home-tilde and configurable truncation
- [ ] `exit_status` module: show non-zero exit codes with color
- [ ] `jobs` module: background job count
- [ ] `cmd_duration` module: show last command duration when above threshold
- [ ] `user` and `host` modules (hidden by default, surface in SSH)
- [ ] `git_branch` module (sync version, cached): branch name + dirty indicator
- [ ] `time` module: optional clock segment

### 1.4 Zsh integration
- [ ] Write `init/shisa.zsh` (eval'd from `.zshrc`)
- [ ] Wire `precmd` to capture `$?`, `$#jobstates`, and elapsed time via `$EPOCHREALTIME`
- [ ] Wire `preexec` to record command start time
- [ ] Set `PROMPT` to `$(shisa prompt --shell=zsh)` with `setopt prompt_subst`
- [ ] Implement fallback prompt (printed if daemon socket missing) that's < 5ms
- [ ] Add `ZSH_VERSION` compat shims for ≥ 5.0

### 1.5 Configuration
- [ ] Define `shisa.toml` schema (modules list, theme, per-module options)
- [ ] Implement TOML parser usage and validation with helpful error spans
- [ ] Ship a `shisa init` command that writes a default config to `~/.config/shisa/shisa.toml`
- [ ] Ship a `shisa explain` command that dumps the resolved module pipeline

### 1.6 Benchmarks (gating)
- [ ] Build `shisa bench` subcommand (runs hyperfine internally on a known workload)
- [ ] Stand up CI benchmark job that runs on every PR vs. main
- [ ] Publish a benchmark dashboard (static HTML, GitHub Pages) updated per merge
- [ ] Add benchmark regression gate (fail PR if p99 warm render regresses > 10%)
- [ ] Build comparison harness vs. starship + p10k + oh-my-posh in same repo
- [ ] Run on nixpkgs and chromium clones; record cold + warm numbers

### 1.7 Tests
- [ ] Unit tests for protocol encode/decode
- [ ] Integration tests using a fake socket + scripted zsh session
- [ ] Snapshot tests for prompt rendering
- [ ] Fuzzer for the wire protocol decoder

## Phase 2 — Async core

- [ ] Implement module execution-class enum and dispatcher
- [ ] Implement placeholder render (returns immediately with a sentinel slot)
- [ ] Implement zsh redraw via `zle reset-prompt` triggered by async-fill notification
- [ ] Implement transient prompt: on `accept-line`, replace prompt with minimal form
- [ ] Build the async git module: spawn git in a worker thread, fill on completion
- [ ] Build the async language-version probe (python/node/rust/go), same model
- [ ] Add cancellation: if the user cd's away, kill in-flight probes for the old cwd
- [ ] Add a per-module slow-warning that logs to `shisad.log` (no command_timeout, but visibility)
- [ ] Add a `--no-async` debug flag for testing fallback paths

## Phase 3 — Caching + fsnotify

- [ ] Build the in-memory cache structure (cwd-keyed map of module-output)
- [ ] Build the fsnotify watcher abstraction (FSEvents on macOS, inotify on Linux)
- [ ] Wire git module to invalidate on `.git/HEAD`, `.git/index`, working-tree changes (debounced)
- [ ] Implement cache eviction policy (LRU, max-N entries, max-age)
- [ ] Implement memoized prompt lookups (cwd + state-tuple → rendered string)
- [ ] Add a `shisa cache` subcommand to dump/inspect cache state
- [ ] Add a `shisa pin <path>` to mark a directory as never-evicted
- [ ] Implement instant prompt: read last-known prompt from cache before daemon RTT completes
- [ ] Add cache warmup: on daemon start, prefetch the user's top-10 most-visited dirs (from zsh history)

## Phase 4 — Cross-shell parity (bash + fish)

- [ ] Author `init/shisa.bash` using `PROMPT_COMMAND`
- [ ] Implement bash duration capture via `DEBUG` trap + `EPOCHREALTIME`
- [ ] Implement bash async redraw via `bind -x` + escape sequence trick (document limitations)
- [ ] Add bash integration tests
- [ ] Author `init/shisa.fish` using `fish_prompt`
- [ ] Implement fish async redraw via fish-native events
- [ ] Add fish integration tests
- [ ] Make instant prompt work in fish (cache-first render before daemon RTT)
- [ ] Document per-shell feature parity in `docs/shells.md`

## Phase 5 — Plugin SDK + Lua sandbox

- [ ] Embed Lua 5.4 (or LuaJIT, evaluate both for sandbox safety)
- [ ] Strip dangerous globals (`os.execute`, `io.popen`, `io.open`, `loadfile`, `dofile`, `require`)
- [ ] Define plugin manifest schema (`capabilities`, `render`, `update`, `name`, `version`)
- [ ] Implement capability gate: fs_read scope, fs_watch scope, exec allow-list, net opt-in
- [ ] Implement `shisa plugin install <git-url>` (clone, audit manifest, prompt user)
- [ ] Implement `shisa plugin trust <name>` for capability escalation
- [ ] Implement `shisa plugin list`, `disable`, `enable`
- [ ] Port `git`, `language version`, `kubernetes-context`, `aws-profile` to the Lua plugin API as references
- [ ] Document the plugin SDK in `docs/plugins.md` with a tutorial
- [ ] Fuzz the Lua↔Zig bridge layer
- [ ] Stand up an awesome-shisa repo listing community plugins
- [ ] Add a `--plugin-sandbox-strict` mode for paranoid users (denies all unknown caps)

## Phase 6 — Nushell + PowerShell + Linux hardening

- [ ] Author `init/shisa.nu` using nu's `PROMPT_COMMAND`
- [ ] Author `init/shisa.ps1` using PowerShell's `prompt` function
- [ ] Implement nu and pwsh redraw mechanisms (or document limitations)
- [ ] Linux: validate inotify watcher count vs. system limits; document raising `max_user_watches`
- [ ] Linux: handle Wayland-only edge cases (none expected, verify)
- [ ] Test under systemd-nspawn, podman, distrobox
- [ ] Test under nix-shell, devenv, flox (these mess with PATH and language versions)
- [ ] Add CI matrix entries for nu + pwsh

## Phase 7 — Theming + starship importer

- [ ] Define theme spec (colors, separators, glyphs, palette refs)
- [ ] Ship 5 built-in themes (nord-dark, gruvbox-rainbow, tokyo-night, plain, minimal-monochrome)
- [ ] Build a theme gallery page on shisa.sh with live previews
- [ ] Build `shisa import-starship <path>` (best-effort TOML translation)
- [ ] Map the top 30 starship modules to Shisa equivalents; document unsupported ones
- [ ] Write a migration guide (`docs/migrate-from-starship.md`)
- [ ] Add interop test: import each preset from starship/preset/* and snapshot the result

## Phase 8 — 1.0 Launch

- [ ] Cut v1.0-rc1, run a 2-week public beta with a feedback issue template
- [ ] Triage and fix all release-blocker issues
- [ ] Author the `brew` formula (homebrew-core PR)
- [ ] Author the AUR PKGBUILD (`shisa-bin` and `shisa-git`)
- [ ] Author the nixpkgs derivation and open PR
- [ ] Author the scoop manifest (for WSL users on Windows)
- [ ] Build install script (`shisa.sh/install`) with checksum verification + signed releases
- [ ] Set up code signing (macOS notarization, sigstore for Linux)
- [ ] Author SBOM publication step in CI
- [ ] Cut v1.0.0
- [ ] Publish launch blog post: "Why we built Shisa"
- [ ] Publish benchmark deep-dive: "How Shisa renders prompts in 2ms"
- [ ] Publish migration guide post
- [ ] Submit Show HN post (Tuesday morning EST)
- [ ] Submit to Hacker News, lobste.rs, r/commandline, r/zsh, r/fishshell, r/nushell, r/rust (cross-promo via Zig)
- [ ] Reach out to dotfile-share creators (devaslife, theprimeagen, fireship) with personal demos
- [ ] Submit to Awesome lists: awesome-zsh, awesome-fish, awesome-cli-apps, awesome-zig

## Phase 9 — Post-GA

- [ ] Stand up the plugin marketplace (static directory, plugins live in user-owned repos, index in shisa.sh/plugins)
- [ ] Add plugin verification: signed manifests, maintainer-vetted "verified" badge
- [ ] Optional: opt-in local-LLM hint plugin (ollama-backed). Off by default. Lives outside core.
- [ ] Optional: cloud-safety plugin pack (prod-warning, k8s-namespace-risk, IAM-principal). Lives outside core.
- [ ] Native Windows support (ReadDirectoryChangesW) — community-led
- [ ] Build a `shisa doctor` subcommand for self-diagnosis (socket, perms, lua plugins, fsnotify limits)
- [ ] Monthly release cadence (first Tuesday of each month)
- [ ] Quarterly retros published as blog posts
- [ ] Bug bounty (small, via GitHub sponsors) for sandbox escapes
- [ ] Submit a talk to FOSDEM 2027 / SCALE / RustConf-Zig-track

## Continuous (every phase)

- [ ] Keep the benchmark dashboard green and public
- [ ] Triage issues weekly, target 7-day first-response SLA
- [ ] Update the changelog on every release (keep-a-changelog format)
- [ ] Update `docs/` whenever a user-facing flag, config field, or module changes
- [ ] Run the fuzzer in CI nightly
- [ ] Run the comparison benchmark vs. starship + p10k + oh-my-posh on every tagged release
- [ ] Respond publicly when starship/p10k/oh-my-posh ship a competing feature; ship our own variant
