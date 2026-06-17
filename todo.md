# Shisa — Task Breakdown

Each line is one discrete unit of work. Phases map to `north-star.md` §14.
Status legend: `[ ]` open  `[~]` in progress  `[x]` done.

---

## Phase 0 — Foundations

- [ ] Reserve `shisa` org/handle on GitHub
- [ ] Reserve `shisa-prompt` crate name as a placeholder (in case we ever ship Rust wrappers)
- [ ] Reserve `shisa.sh` domain for landing + install script
- [ ] Reserve `@shisa` on npm in case of node-side install tooling
- [x] Decide canonical README/landing copy + the one-line pitch
- [x] Author `LICENSE` (MIT) at repo root
- [x] Author `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)
- [x] Author `CONTRIBUTING.md` (build, test, RFC process)
- [x] Author `SECURITY.md` (responsible disclosure address, scope)
- [x] Set up `.editorconfig`, `.gitattributes`
- [x] Choose Zig toolchain version and pin in `build.zig.zon`
- [x] Initialize `build.zig` skeleton (debug + release + benchmark steps)
- [x] Set up GitHub Actions matrix: macOS-14, ubuntu-22.04, ubuntu-24.04
- [x] Configure release-please / cargo-dist equivalent for Zig (manual tag-driven release for v0)
- [x] Set up sccache-equivalent caching for Zig builds in CI
- [x] Write RFC-0001: Daemon wire protocol (framing, message types, versioning)
- [x] Write RFC-0002: Module execution classes (sync, async, cached)
- [x] Write RFC-0003: Lua plugin capability manifest schema
- [x] Write RFC-0004: Cache invalidation rules (per-module fsnotify scope)
- [x] Set up `rfcs/` directory and a template
- [x] Set up issue templates (bug, perf regression, plugin request, RFC)
- [x] Set up PR template (checklist: tests, benchmarks-run, RFC-referenced)
- [ ] Create project board with milestones aligned to phases
- [ ] Stand up minimal landing page on `shisa.sh` (single HTML, install one-liner, link to repo)
- [x] Write the architecture overview doc (`docs/architecture.md`)
- [x] Pick the wire protocol (length-prefixed JSON per RFC-0001)
- [x] Decide socket path convention (`$XDG_RUNTIME_DIR/shisa.sock` on Linux, `~/Library/Caches/shisa/shisa.sock` on macOS)

## Phase 1 — Single-shell MVP (zsh on macOS)

### 1.1 Daemon skeleton
- [x] `shisad` entry: parse CLI args, daemonize with `posix_spawn` or fork+setsid
- [x] Implement single-instance lock via flock on the socket path
- [x] Implement unix-domain socket server (accept loop, per-conn handler)
- [x] Implement graceful shutdown on SIGTERM/SIGINT (drain in-flight requests, unlink socket)
- [x] Implement crash-restart supervisor (separate `shisa supervisor` binary or `--supervise` flag)
- [x] Implement structured logging to `~/Library/Logs/shisa/shisad.log`
- [x] Implement log rotation (size-based, 5×10MB ring)
- [x] Implement `shisad --version`, `--health`, `--metrics` admin endpoints

### 1.2 Wire protocol v0
- [x] Define request frame (length-prefixed JSON): `{cwd, exit, jobs, duration, shell, cols, rows}`
- [x] Define response frame: `{prompt, redraw_token?}`
- [x] Implement encoder/decoder in Zig with fuzz tests
- [x] Implement client library (`shisa-client.zig`) for use by `shisa prompt`
- [x] Implement `shisa prompt` CLI that connects to daemon and prints

### 1.3 Sync modules (v0)
- [x] `cwd` module: display current directory with home-tilde and configurable truncation
- [x] `exit_status` module: show non-zero exit codes with color
- [x] `jobs` module: background job count
- [x] `cmd_duration` module: show last command duration when above threshold
- [x] `user` and `host` modules (hidden by default, surface in SSH)
- [x] `git_branch` module (sync version, cached): branch name + dirty indicator
- [x] `time` module: optional clock segment

### 1.4 Zsh integration
- [x] Write `init/shisa.zsh` (eval'd from `.zshrc`)
- [x] Wire `precmd` to capture `$?`, `$#jobstates`, and elapsed time via `$EPOCHREALTIME`
- [x] Wire `preexec` to record command start time
- [x] Set `PROMPT` to `$(shisa prompt --shell=zsh)` with `setopt prompt_subst`
- [x] Implement fallback prompt (printed if daemon socket missing) that's < 5ms
- [x] Add `ZSH_VERSION` compat shims for ≥ 5.0

### 1.5 Configuration
- [x] Define `shisa.toml` schema (modules list, theme, per-module options)
- [x] Implement TOML parser usage and validation with helpful error spans
- [x] Ship a `shisa init` command that writes a default config to `~/.config/shisa/shisa.toml`
- [x] Ship a `shisa explain` command that dumps the resolved module pipeline

### 1.6 Benchmarks (gating)
- [x] Build `shisa bench` subcommand (runs hyperfine internally on a known workload)
- [x] Stand up CI benchmark job that runs on every PR vs. main
- [x] Publish a benchmark dashboard (static HTML, GitHub Pages) updated per merge
- [x] Add benchmark regression gate (fail PR if p99 warm render regresses > 10%)
- [x] Build comparison harness vs. starship + p10k + oh-my-posh in same repo
- [ ] Run on nixpkgs and chromium clones; record cold + warm numbers

### 1.7 Tests
- [x] Unit tests for protocol encode/decode
- [x] Integration tests using a fake socket + scripted zsh session
- [x] Snapshot tests for prompt rendering
- [x] Fuzzer for the wire protocol decoder

## Phase 2 — Async core

- [x] Implement module execution-class enum and dispatcher
- [x] Implement placeholder render (returns immediately with a sentinel slot)
- [x] Implement zsh redraw via `zle reset-prompt` triggered by async-fill notification
- [x] Implement transient prompt: on `accept-line`, replace prompt with minimal form
- [x] Build the async git module: spawn git in a worker thread, fill on completion
- [x] Build the async language-version probe (python/node/rust/go), same model
- [x] Add cancellation: if the user cd's away, kill in-flight probes for the old cwd
- [x] Add a per-module slow-warning that logs to `shisad.log` (no command_timeout, but visibility)
- [x] Add a `--no-async` debug flag for testing fallback paths

## Phase 3 — Caching + fsnotify

- [x] Build the in-memory cache structure (cwd-keyed map of module-output)
- [x] Build the fsnotify watcher abstraction (FSEvents on macOS, inotify on Linux)
- [x] Wire git module to invalidate on `.git/HEAD`, `.git/index`, working-tree changes (debounced)
- [x] Implement cache eviction policy (LRU, max-N entries, max-age)
- [x] Implement memoized prompt lookups (cwd + state-tuple → rendered string)
- [x] Add a `shisa cache` subcommand to dump/inspect cache state
- [x] Add a `shisa pin <path>` to mark a directory as never-evicted
- [x] Implement instant prompt: read last-known prompt from cache before daemon RTT completes
- [x] Add cache warmup: on daemon start, prefetch the user's top-10 most-visited dirs (from zsh history)

## Phase 4 — Cross-shell parity (bash + fish)

- [x] Author `init/shisa.bash` using `PROMPT_COMMAND`
- [x] Implement bash duration capture via `DEBUG` trap + `EPOCHREALTIME`
- [x] Implement bash async redraw via `bind -x` + escape sequence trick (document limitations)
- [x] Add bash integration tests
- [x] Author `init/shisa.fish` using `fish_prompt`
- [x] Implement fish async redraw via fish-native events
- [x] Add fish integration tests
- [x] Make instant prompt work in fish (cache-first render before daemon RTT)
- [x] Document per-shell feature parity in `docs/shells.md`

## Phase 5 — Plugin SDK + Lua sandbox

- [x] Embed Lua 5.4 (or LuaJIT, evaluate both for sandbox safety)
- [x] Strip dangerous globals (`os.execute`, `io.popen`, `io.open`, `loadfile`, `dofile`, `require`)
- [x] Define plugin manifest schema (`capabilities`, `render`, `update`, `name`, `version`)
- [x] Implement capability gate: fs_read scope, fs_watch scope, exec allow-list, net opt-in
- [x] Implement `shisa plugin install <git-url>` (clone, audit manifest, prompt user)
- [x] Implement `shisa plugin trust <name>` for capability escalation
- [x] Implement `shisa plugin list`, `disable`, `enable`
- [x] Port `git`, `language version`, `kubernetes-context`, `aws-profile` to the Lua plugin API as references
- [x] Document the plugin SDK in `docs/plugins.md` with a tutorial
- [x] Fuzz the Lua↔Zig bridge layer
- [ ] Stand up an awesome-shisa repo listing community plugins
- [x] Add a `--plugin-sandbox-strict` mode for paranoid users (denies all unknown caps)

## Phase 6 — Nushell + PowerShell + Linux hardening

- [x] Author `init/shisa.nu` using nu's `PROMPT_COMMAND`
- [x] Author `init/shisa.ps1` using PowerShell's `prompt` function
- [x] Implement nu and pwsh redraw mechanisms (or document limitations)
- [x] Linux: validate inotify watcher count vs. system limits; document raising `max_user_watches`
- [ ] Linux: handle Wayland-only edge cases (none expected, verify)
- [ ] Test under systemd-nspawn, podman, distrobox
- [ ] Test under nix-shell, devenv, flox (these mess with PATH and language versions)
- [x] Add CI matrix entries for nu + pwsh

## Phase 7 — Theming + starship importer

- [x] Define theme spec (colors, separators, glyphs, palette refs)
- [x] Ship 5 built-in themes (nord-dark, gruvbox-rainbow, tokyo-night, plain, minimal-monochrome)
- [ ] Build a theme gallery page on shisa.sh with live previews
- [x] Build `shisa import-starship <path>` (best-effort TOML translation)
- [x] Map the top 30 starship modules to Shisa equivalents; document unsupported ones
- [x] Write a migration guide (`docs/migrate-from-starship.md`)
- [x] Add interop test: import each preset from starship/preset/* and snapshot the result

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
- [x] Build a `shisa doctor` subcommand for self-diagnosis (socket, perms, lua plugins, fsnotify limits)
- [ ] Monthly release cadence (first Tuesday of each month)
- [ ] Quarterly retros published as blog posts
- [ ] Bug bounty (small, via GitHub sponsors) for sandbox escapes
- [ ] Submit a talk to FOSDEM 2027 / SCALE / RustConf-Zig-track

## Continuous (every phase)

- [ ] Keep the benchmark dashboard green and public
- [ ] Triage issues weekly, target 7-day first-response SLA
- [ ] Update the changelog on every release (keep-a-changelog format)
- [ ] Update `docs/` whenever a user-facing flag, config field, or module changes
- [x] Run the fuzzer in CI nightly
- [ ] Run the comparison benchmark vs. starship + p10k + oh-my-posh on every tagged release
- [ ] Respond publicly when starship/p10k/oh-my-posh ship a competing feature; ship our own variant

---

# Plugin Packs — Phases 10+

These run in parallel to core hardening. Pack work **must not** regress core perf targets defined in north-star.md §10.

## Phase 10 — VCS moat pack (`shisa.vcs`)

### 10.1 Jujutsu (jj) — Tier 1
- [x] Detect jj repos (`.jj/` directory)
- [x] Read jj operation log via `jj op log --no-graph` (cached, fsnotify on `.jj/op_heads`)
- [x] Show current change ID (short hash), description first line, divergence
- [x] Show conflict state (`jj`'s first-class conflicts) inline
- [x] Show working-copy commit vs. parent commits
- [x] Async update on jj operations
- [x] Snapshot tests against fixture jj repos
- [x] Benchmark on a 10k-change jj repo

### 10.2 Sapling (sl) — Tier 1
- [x] Detect sapling repos (`.sl/` directory)
- [x] Read sapling state via `sl status --root-relative` (cached, fsnotify on `.sl/store`; `--json` unsupported in Sapling 0.2.20260522)
- [x] Show smartlog position (current commit in the stack)
- [x] Show bookmark / branch
- [x] Snapshot tests against fixture sapling repos

### 10.3 Mercurial (hg) — Tier 1
- [x] Detect hg repos (`.hg/`)
- [x] Read state via `hg summary --remote` (cached)
- [x] Show branch, bookmark, topic (evolve), draft/public phase
- [x] Handle mq queues if active

### 10.4 Stacked-diff awareness (`shisa.vcs.stack`)
- [x] Detect Graphite (`gt`): `.graphite_repo_config`
- [x] Detect ghstack: branch naming + `.ghstackrc`
- [x] Detect spr / git-spr: `.git/refs/spr/`
- [x] Detect `st`: meta files
- [x] Detect git-spice (`gs`): meta files
- [x] Detect git-town: `.git-town-branches.yml`
- [x] Detect GitHub-native stacked PRs (`gh stack`) via remote config
- [x] Render stack position (e.g., `2/5 ↑↓`)
- [x] Add a `shisa stack` CLI to dump the detected stack as text

### 10.5 Worktree (`shisa.vcs.worktree`)
- [x] Show `wt:<name>` when cwd is inside a worktree
- [x] `shisa worktrees` CLI lists all worktrees, marks active
- [x] Multi-worktree dirty-tree warning across worktrees

### 10.6 Community-tier plugins (templates only)
- [x] Publish a Fossil plugin template
- [x] Publish a Pijul plugin template
- [x] Publish a Bazaar/Breezy plugin template
- [ ] Link to community repo in plugin marketplace

### 10.7 Tests & benches
- [x] Per-VCS fixture corpus checked into `test/fixtures/vcs/<vcs>/`
- [x] CI matrix runs each VCS module against fixtures on every PR
- [x] Public benchmark vs. starship git on the same repos for parity confirmation

## Phase 11 — Cloud-safety pack (`shisa.cloud`)

### 11.1 Multi-cloud context segment (`cloud_ctx`)
- [x] AWS profile from `AWS_PROFILE` env + `~/.aws/config` parse
- [x] GCP project from active Cloud SDK config file (cached, fsnotify on `~/.config/gcloud/`)
- [x] Azure subscription from `~/.azure/azureProfile.json` (cached, fsnotify on `~/.azure/azureProfile.json`)
- [x] Kubernetes context+namespace from kubeconfig (fsnotify on `KUBECONFIG`)
- [x] Render unified segment with iconography per cloud
- [x] Configurable show/hide per cloud
- [x] Fast-path: never spawn subprocesses on the hot path; rely on cached file reads

### 11.2 Risk-tier classifier (`risk_tier`)
- [x] Define regex defaults (`prod`, `production`, `live`, `*-prd-*` → prod; `stg`, `staging` → staging; `dev`, `sandbox` → dev)
- [x] User-defined rules in `~/.config/shisa/risk_tiers.toml`
- [x] Apply tier color to prompt's background bar (configurable)
- [x] Per-cloud override (e.g., AWS profile=prod, k8s=dev → use max-tier=prod)
- [x] `shisa cloud explain` CLI to print why a tier was chosen

### 11.3 Pre-exec prod guard (`prod_guard`)
- [x] Implement pre-exec hook protocol across shells (zsh `preexec`, bash `DEBUG` trap, fish `fish_preexec`)
- [x] Daemon-side classifier on command + tier
- [x] Built-in destructive-pattern blocklist (kubectl delete/drain, terraform destroy, aws ec2 terminate, aws s3 rb, gcloud * delete, rm -rf, dd of=/dev/, mkfs, DROP TABLE)
- [x] Typed-confirm UX (must type the tier name to proceed)
- [x] `--force` bypass (logged)
- [x] Audit log to `~/.local/state/shisa/prod_guard.jsonl`
- [x] Bypass-log review CLI (`shisa cloud audit`)
- [x] Fuzz the classifier against a corpus of dangerous-looking-but-safe commands (`kubectl get`, `terraform plan`)

### 11.4 IAM whoami (`iam_whoami`)
- [x] AWS STS GetCallerIdentity cached value
- [x] GCP `gcloud auth list` cached
- [x] Azure `az account show` cached
- [x] k8s `kubectl config current-context` user

### 11.5 SSO expiry (`sso_expiry`)
- [x] AWS SSO: read `~/.aws/sso/cache/*.json`, find soonest `expiresAt`
- [x] gcloud: parse `gcloud auth list --format=json` for expiry
- [x] Azure: parse `~/.azure/accessTokens.json`
- [x] HashiCorp Vault: read `~/.vault-token` lease info
- [x] 1Password CLI: `op signin status` cache
- [x] Render warning when any < 30 min remain (configurable)

### 11.6 IaC workspace (`iac_workspace`)
- [x] Terraform: read `.terraform/environment` or current workspace from state
- [x] Pulumi: read `Pulumi.<stack>.yaml` + active stack
- [x] CDK: read `cdk.json` + `cdk.context.json`
- [x] OpenTofu: same as Terraform
- [x] Render workspace + lock indicator
- [x] Pre-exec warn if workspace appears stale or remotely locked

### 11.7 Region drift (`region_drift`)
- [x] AWS: compare `$AWS_REGION` / `$AWS_DEFAULT_REGION` to profile-configured region
- [x] GCP: compare `$CLOUDSDK_COMPUTE_REGION` to gcloud config
- [x] Azure: compare env vars to active subscription default
- [x] Render warning segment when drift detected

### 11.8 Cost glance (`cost_glance`) — optional, heavy
- [x] AWS Cost Explorer client (read-only, IAM least-priv guide)
- [x] GCP Billing API client
- [x] Azure Cost Management client
- [x] Background hourly refresh in the daemon (off-thread)
- [x] Cache to `~/.local/state/shisa/cost.json`
- [x] Render compact MTD spend per cloud
- [x] Document the IAM permissions required and the privacy implications (this calls cloud APIs!)

### 11.9 VPN status (`vpn_status`)
- [x] Detect Wireguard interface up (parse `wg show`)
- [x] Detect Tailscale (`tailscale status --json`)
- [x] Detect NetBird, Cloudflare WARP, Zerotier
- [x] macOS: detect OpenVPN / IKEv2 system VPN via `scutil`
- [x] Linux: detect via NetworkManager d-bus
- [x] Render compact "vpn:<name>" segment when active

### 11.10 SSH target (`ssh_target`)
- [x] Detect inside SSH session via `$SSH_CONNECTION`
- [x] Classify remote host using risk_tier rules
- [x] Render `→ host (prod)` segment when remote

### 11.11 Container provenance (`container_provenance`)
- [x] Detect docker (`/.dockerenv`)
- [x] Detect podman (cgroups inspection)
- [x] Detect devcontainer (`$REMOTE_CONTAINERS`)
- [x] Detect nix-shell (`$IN_NIX_SHELL`)
- [x] Detect distrobox / toolbx (env vars / marker files)
- [x] Detect Kubernetes pod context (env vars / `/var/run/secrets/kubernetes.io/`)
- [x] Render `[docker:web]` style segment

### 11.12 Tests & benches
- [x] Mock cloud config fixtures under `test/fixtures/cloud/`
- [x] Snapshot tests for each segment
- [x] prod_guard fuzz suite
- [x] Benchmark `cloud_ctx` cold path < 30ms, warm < 1ms
- [x] Ship a `shisa cloud doctor` for self-diagnosis

## Phase 12 — AI plugin pack (`shisa.ai`)

### 12.1 Ollama integration
- [x] Detect ollama install + running daemon
- [x] Pull recommended small model (final choice TBD after benchmark: `qwen2.5:1.5b` / `gemma3:1b` / `phi3:mini`)
- [x] Implement Ollama HTTP client in Zig
- [x] Stream tokens with cancellation
- [x] Benchmark first-token latency, tokens/sec, peak RAM
- [x] Ship a `shisa ai bench` subcommand that reports local model perf

### 12.2 Next-command suggestion (`nextcmd`)
- [x] Hotkey integration per shell (zsh widget, bash bind -x, fish key binding, nu / pwsh equivalents)
- [x] Context builder: history slice + cwd + last command + last exit code
- [x] Prompt template + few-shot examples checked into repo
- [x] Inline preview UX (renders below the prompt line; ghost text)
- [x] Accept (tab) / reject (esc) / next (alt-]) controls
- [ ] Bench: median round-trip < 800ms on a 2020 MacBook Air

### 12.3 Natural language to command (`nl2cmd`)
- [x] Detect `?? ` prefix at start of input line
- [x] Submit input to model with NL→cmd prompt template
- [x] Render candidate command(s) with confidence
- [x] Confirmation gate before exec (always; never auto-run)
- [ ] Log every NL→cmd to `~/.local/state/shisa/nl2cmd.jsonl`

### 12.4 Risk explainer (`risk`)
- [ ] Rules-engine first (fast, deterministic, same blocklist as prod_guard)
- [ ] Optional SLM second pass on borderline commands
- [ ] Render "this will delete N files in /etc" style annotations
- [ ] Pre-exec gate integration

### 12.5 Command explainer (`explain`)
- [ ] Hotkey to explain current input
- [ ] Prompt template + flag-aware breakdown
- [ ] Cache explanations (same command → same explanation) per session

### 12.6 Error fixer (`errfix`)
- [ ] Hook into last command's stderr capture
- [ ] On non-zero exit, surface a one-line "shisa: try `<x>`?" hint
- [ ] User opt-in per non-zero exit (don't be noisy)
- [ ] Maintain a curated set of common error → fix patterns (rules-first, SLM-second)

### 12.7 Semantic history search (`histsearch`)
- [ ] Local embedding model recipe (`nomic-embed-text` via Ollama, or candle/llama.cpp embedding)
- [ ] Index history into a local vector store (sqlite-vss / lancedb in-process)
- [ ] Hotkey to fuzzy-semantic-search history
- [ ] Optional atuin adapter (read atuin's sqlite DB if present)

### 12.8 cd hint (`cdhint`)
- [ ] Rule-based project detector (package.json → node; Cargo.toml → rust; etc.)
- [ ] Compact one-line hint after cd into a recognized project (configurable / disable per dir)
- [ ] No model required; pure rules

### 12.9 Privacy & audit
- [ ] Enforce `net` capability gate (no network unless explicitly granted)
- [ ] Per-provider trust (`shisa plugin trust shisa.ai --net=openai`)
- [ ] Local redaction rules (`shisa ai redact` CLI to edit/test rules)
- [ ] Audit log of every cloud request (hash-only by default)
- [ ] Document privacy contract in `docs/ai-privacy.md`
- [ ] Add a `shisa ai status` showing what's local, what's cloud, what's logged

### 12.10 Provider abstraction (optional cloud)
- [ ] OpenAI provider (opt-in)
- [ ] Anthropic provider (opt-in)
- [ ] Gemini provider (opt-in)
- [ ] LM Studio provider (local but non-Ollama)
- [ ] llama.cpp direct (local, no daemon)
- [ ] Provider switch via plugin config; daemon enforces capability

### 12.11 Tests & benches
- [ ] Mock-model harness for deterministic tests
- [ ] Prompt-regression suite (snapshot of model outputs against curated examples; tolerate drift)
- [ ] Cold-model latency benchmark
- [ ] Warm-model latency benchmark
- [ ] Memory ceiling benchmark per supported model

## Phase 13 — Activity & focus pack (`shisa.activity`)

- [ ] `long_running` indicator (timer when foreground cmd > N seconds)
- [ ] `cmd_complete_bell` (terminal bell / OSC-9 / notify-send / macOS UserNotifications)
- [ ] `tmux_pane` segment (pane/window when inside tmux)
- [ ] `right_prompt` (right-aligned secondary segment, RPS in zsh / fish_right_prompt in fish)
- [ ] Per-shell ergonomic shims for right_prompt where shell support is partial
- [ ] Tests for tmux integration via expect/pexpect scripts

## Phase 14 — Plugin marketplace polish

- [ ] Static marketplace index hosted on shisa.sh (JSON manifest of community plugins)
- [ ] Signature scheme: plugin manifests signed with maintainer minisign / sigstore
- [ ] `verified` badge in `shisa plugin list`
- [ ] `shisa plugin install <name>` from marketplace
- [ ] `shisa plugin search <query>`
- [ ] `shisa plugin doctor` for plugin self-diagnosis
- [ ] Community moderation policy (`docs/plugin-policy.md`)
- [ ] Plugin author quickstart (`docs/authoring-plugins.md`)
- [ ] Sample plugin template repo (`shisa-plugin-template`)
- [ ] Bug bounty for sandbox escapes (small, via GitHub sponsors)

## Continuous (extended)

- [ ] Quarterly pack-perf review: each pack's overhead measured against baseline core
- [x] Document every plugin capability and its risk in `docs/capabilities.md`
- [x] Maintain `docs/pack-status.md` showing incubation / graduated / vetted / EOL state per pack
- [ ] Triage pack issues at the pack repo level, not the core repo, once graduated
- [ ] Run the pack benchmark suite weekly on the main branch

---

# Implementation Specs & Quality Phases (Phases 15+)

Each phase below is normative for v1.0 quality. Tasks here are *not* deferred — many run interleaved with core phases. Sequencing inside each phase is suggested only.

## Phase 15 — Wire protocol implementation

### 15.1 Protocol library
- [ ] Implement length-prefixed JSON framer/deframer in Zig (`src/proto/frame.zig`)
- [ ] u32 BE length header; validate against 1 MiB cap
- [ ] Property tests: roundtrip arbitrary payloads; corruption detection
- [ ] Fuzz harness for the deframer (libFuzzer via Zig)
- [ ] Benchmark: deframe 100k frames in < 1 s on baseline machine

### 15.2 Request/response schemas
- [ ] Zig structs for `Request`, `Response`, `Error` mirroring §26.2–§26.5
- [ ] JSON encoder/decoder generated via comptime
- [ ] Unknown-field tolerance for forward-compat
- [ ] Required-field validation with structured error
- [ ] Snapshot tests for every (op × shape) combination

### 15.3 Ops
- [ ] `render` — full request/response path
- [ ] `render_continue` — async fill-in
- [ ] `health` — minimal ok/not-ok
- [ ] `metrics` — JSON metrics dump
- [ ] `reload` — re-read config + plugins
- [ ] `version` — daemon + protocol version
- [ ] `subscribe` — editor stream (Phase 16)

### 15.4 Error codes
- [ ] Define enum: `E_VERSION`, `E_OVERSIZE`, `E_MALFORMED`, `E_NOT_READY`, `E_PLUGIN_TIMEOUT`, `E_CAPABILITY_DENIED`, `E_INTERNAL`
- [ ] Document each in `docs/protocol/errors.md`
- [ ] Each error includes structured context fields for machine consumption

### 15.5 Versioning + RFC binding
- [ ] Write RFC-0005: Wire protocol v1 (canonical reference)
- [ ] CI gate: protocol changes require RFC update in same PR
- [ ] Generate a JSON Schema for external consumers (editors, plugins, scripts)

## Phase 16 — Editor integration

### 16.1 `subscribe` op implementation
- [ ] Bidirectional NDJSON stream over connected socket
- [ ] Topic subscription with reference-counting per-topic
- [ ] Snapshot then delta updates
- [ ] Backpressure: drop if client slower than producer (configurable)
- [ ] Disconnect cleanly, free state

### 16.2 Read-only enforcement
- [ ] Daemon-side allowlist of read-only ops on subscribe connections
- [ ] Reject any mutation attempt with `E_READONLY`
- [ ] Tests verifying editor cannot bypass `prod_guard`

### 16.3 Helix bridge
- [ ] Write `contrib/editor-bridges/helix-shisa.toml`
- [ ] Document custom statusline syntax + how to plug in
- [ ] Sample config with `cloud_ctx`, `vcs.summary`, `risk_tier`
- [ ] Sanity test on Helix nightly

### 16.4 Neovim bridge (`shisa.nvim`)
- [ ] Small Lua plugin under `contrib/editor-bridges/shisa.nvim/`
- [ ] Lualine + heirline integration examples
- [ ] Autocmd to refresh on `DirChanged`
- [ ] Unit tests via `plenary.nvim` test harness

### 16.5 Zed bridge
- [ ] Zed extension scaffold under `contrib/editor-bridges/shisa-zed/`
- [ ] Submit to Zed extensions marketplace
- [ ] Document the manifest + signing requirements

### 16.6 Bridge tests + docs
- [ ] Documented "writing a Shisa bridge in 50 lines" guide
- [ ] Sample TypeScript bridge for VS Code (community-quality, no commitment)
- [ ] Integration tests using mock editor harnesses

## Phase 17 — Governance + Vouch integration

### 17.1 Vouch adoption
- [ ] Add `VOUCHES` text file at repo root (POSIX-parseable)
- [ ] Bootstrap with founder as only vouched entry
- [ ] Document the format in `docs/governance/vouch.md`
- [ ] Add `shisa vouch verify` CLI subcommand
- [ ] PR template asks: "Are you vouched? If not, expect a 2-vouched-reviewer review."

### 17.2 RFC process
- [ ] Create `rfcs/` directory + template
- [ ] Migrate existing RFC-000{1..5} into the template format
- [ ] Add RFC index in `rfcs/README.md`
- [ ] CI gate: protocol/security/plugin-API changes require an RFC link in the PR body
- [ ] 14-day public comment window automation via GitHub label

### 17.3 Maintainer onboarding
- [ ] Write `docs/governance/maintainer-onboarding.md`
- [ ] Document the steering-group transition triggers from §35.2
- [ ] Publish current state on shisa.sh/governance

### 17.4 Code of conduct
- [ ] Adopt Contributor Covenant 2.1 verbatim
- [ ] Document enforcement chain
- [ ] Set up project email alias + private appeals tracking

## Phase 18 — Migration importers (beyond starship)

### 18.1 Powerlevel10k importer
- [ ] Parse p10k zsh config (extract `POWERLEVEL9K_*` settings)
- [ ] Map elements to Shisa modules with a coverage table
- [ ] Translate left/right prompt layout
- [ ] Handle p10k's "instant_prompt" feature (map to Shisa's instant prompt)
- [ ] Emit `migration-notes.md` for unsupported elements

### 18.2 Oh-my-posh importer
- [ ] Parse oh-my-posh JSON/YAML themes
- [ ] Map segments to Shisa modules with a coverage table
- [ ] Translate template strings to Shisa's layout syntax
- [ ] Color mapping: oh-my-posh palette → Oklab → Shisa palette
- [ ] Emit `migration-notes.md`

### 18.3 Tide importer
- [ ] Parse tide fish settings (`tide configure` output)
- [ ] Map tide items to Shisa modules
- [ ] Document fish-specific quirks that don't translate
- [ ] Emit `migration-notes.md`

### 18.4 Pure importer
- [ ] Minimal mapping: pure → Shisa "pure" preset
- [ ] Document as a smallest-possible config
- [ ] Smoke test against pure zsh + fish variants

### 18.5 Importer test corpus
- [ ] Vendor representative configs of each tool under `test/fixtures/migration/`
- [ ] Snapshot the resulting Shisa configs
- [ ] CI gate: snapshot drift requires review

## Phase 19 — Documentation site + tutorials

### 19.1 Docs site
- [ ] mdBook scaffold under `docs/`
- [ ] Build pipeline: PR previews via GitHub Actions
- [ ] Deploy to shisa.sh/docs
- [ ] Search: stork-search or pagefind integration

### 19.2 Quickstart
- [ ] Page: install + 5-min to a working prompt (zsh + bash + fish + nu + pwsh tabs)
- [ ] Animated terminal gif (asciinema-recorded, no JS dep)
- [ ] Troubleshooting collapsible block

### 19.3 Recipes
- [ ] Recipe: "k8s context safety in 60 seconds"
- [ ] Recipe: "AI hotkey suggestion with local model"
- [ ] Recipe: "Stacked-diff workflow with Graphite + Shisa"
- [ ] Recipe: "Custom theme inheriting from okiya-night"
- [ ] Recipe: "Migrating from Powerlevel10k step-by-step"
- [ ] Recipe: "Plugin in 30 lines of Lua"
- [ ] Recipe: "Running Shisa over SSH without slowing the prompt"
- [ ] Recipe: "Configuring `--a11y` for screen readers"

### 19.4 Reference
- [ ] Generate config-schema docs from `build.zig`
- [ ] Generate CLI docs from `shisa --help` tree (cobra-like extraction)
- [ ] Generate plugin-API docs from Zig source annotations
- [ ] Auto-publish on every release

### 19.5 Internals
- [ ] Threat model write-up
- [ ] Profiling notes
- [ ] Cache architecture deep-dive
- [ ] Why we picked Zig

### 19.6 Videos
- [ ] "Why Shisa" — 3-minute project intro
- [ ] "5-min Setup" — install walkthrough
- [ ] "Plugin in 10 lines" — Lua plugin tutorial
- [ ] Captions + transcripts checked into repo
- [ ] Publish on YouTube + PeerTube mirror

### 19.7 Style + linting
- [ ] Adopt `vale` style guide
- [ ] CI gate on docs PRs
- [ ] Style guide page

## Phase 20 — Release engineering + supply chain

### 20.1 Reproducible builds
- [ ] Pin Zig version + lockfile for all deps
- [ ] Document the deterministic build invocation
- [ ] Verify bit-identical artifacts across two CI hosts
- [ ] Publish reproducibility status badge

### 20.2 SBOM
- [ ] Generate SPDX SBOM on every tagged release
- [ ] Publish alongside binary in GitHub Release
- [ ] CI gate: SBOM diff diff'd against previous release for review

### 20.3 Signing (Sigstore)
- [ ] cosign keyless signing in CI (OIDC via GitHub Actions identity)
- [ ] Publish signatures + Rekor log links
- [ ] `shisa update --verify` validates signature before applying
- [ ] Document key-distrust + rotation procedure

### 20.4 SLSA
- [ ] Achieve SLSA Level 2 attestation
- [ ] Publish provenance per release
- [ ] Roadmap to SLSA Level 3 (hermetic builds)

### 20.5 Distribution channels
- [ ] Homebrew formula (tap → core)
- [ ] AUR `shisa-bin` PKGBUILD
- [ ] AUR `shisa-git` PKGBUILD
- [ ] Nixpkgs derivation
- [ ] Scoop manifest (WSL)
- [ ] AppImage build pipeline
- [ ] Flatpak manifest (community)
- [ ] Snap (community)
- [ ] DEB packaging script
- [ ] RPM packaging script (Fedora, Suse)
- [ ] `curl shisa.sh/install` script + checksum verify

### 20.6 Release automation
- [ ] One-button monthly release script
- [ ] Generate changelog from commits + RFCs since last release
- [ ] Auto-create GitHub Release draft
- [ ] Post-release: bump dev version + notify channels

### 20.7 Deprecation policy
- [ ] Document the one-major-overlap rule
- [ ] Add `shisa doctor` warnings for deprecated APIs in use
- [ ] Track deprecations in `docs/deprecations.md`

## Phase 21 — Accessibility (WCAG AA + a11y mode)

### 21.1 Contrast enforcement
- [ ] Implement Oklab contrast calculator
- [ ] `shisa theme validate` enforces ≥ 4.5:1 (text) and ≥ 3:1 (UI signals)
- [ ] CI gate: refuse new themes failing contrast

### 21.2 Non-color signal layer
- [ ] Every risk-encoding color also has a glyph
- [ ] Every glyph also has an ASCII fallback
- [ ] Every prompt segment carries an `a11y` string
- [ ] `shisa render --explain-a11y` dumps the alt-text for the current prompt

### 21.3 `--a11y` mode
- [ ] `shisa init --a11y` writes a config with colors stripped + glyphs ASCII
- [ ] Built-in `a11y` theme passing AAA on ASCII
- [ ] `shisa render --a11y` flag for one-shot test
- [ ] Document why a11y mode is opinionated (no override of certain signals)

### 21.4 Screen-reader plumbing
- [ ] Emit OSC-7 (cwd) per prompt
- [ ] Custom OSC sequence for a11y summary (documented + reserved)
- [ ] Optional `shisa.a11y.live` plugin: announce risk-tier transitions
- [ ] Test on macOS VoiceOver
- [ ] Test with NVDA on Windows Terminal
- [ ] Test with Orca on Linux

### 21.5 Keyboard-only
- [ ] Audit every CLI command for keyboard-only operability
- [ ] No interactive TUIs without `--interactive` flag
- [ ] Bell + notification preferences settable via CLI args
- [ ] Documented behavior table

### 21.6 External audit
- [ ] Commission a one-time a11y audit before v1.0
- [ ] Publish audit findings + remediation
- [ ] Plan annual re-audits

## Phase 22 — Internationalization

### 22.1 Message catalog
- [ ] Adopt gettext-compatible format under `i18n/`
- [ ] Initial language: en-US
- [ ] Extract all user-facing strings to catalog
- [ ] Generated docs include translation status table

### 22.2 Bidi / RTL
- [ ] Detect RTL locale at session start
- [ ] Segment-order reversal opt-in
- [ ] Fixture strings for Arabic, Hebrew, Persian
- [ ] Snapshot tests for RTL rendering

### 22.3 CJK width
- [ ] Implement UAX-11 East Asian Width handling
- [ ] Width-aware truncation
- [ ] Fixture strings for Chinese, Japanese, Korean
- [ ] Snapshot tests

### 22.4 Translation workflow
- [ ] Document the translation contribution flow
- [ ] Use Weblate or similar (community-hosted) for translations
- [ ] CI gate: locale catalog diffs flagged for review

## Phase 23 — Brand + visual identity

### 23.1 Mascot + logo
- [ ] Commission a shisa-lion-dog mascot illustration
- [ ] Generate logo set: 16×, 32×, 64×, 128×, 256×, SVG
- [ ] Repo icon + favicon + landing hero
- [ ] License logo CC-BY-SA so community can remix

### 23.2 Visual tokens
- [ ] Define primary + accent palette
- [ ] Pick prose + mono fonts
- [ ] Style tokens published in `brand/tokens.json`
- [ ] Brand guide page at shisa.sh/brand

### 23.3 Landing page
- [ ] Single-page landing at shisa.sh
- [ ] Above-the-fold: pitch + install one-liner + asciinema demo
- [ ] Sections: why, install, plugins, benchmarks, community
- [ ] Lighthouse score ≥ 95 on perf + a11y
- [ ] No analytics; static only

### 23.4 Sticker + swag
- [ ] Sticker design (CC-BY) for conference giveaways
- [ ] Mug, t-shirt designs available on a print-on-demand
- [ ] Funds offset community costs (transparent on Open Collective)

## Phase 24 — Advanced git states (deep coverage)

### 24.1 Operation states
- [ ] Detect rebase (in-progress / interactive / merge variant)
- [ ] Detect merge (in-progress)
- [ ] Detect cherry-pick (in-progress / sequence)
- [ ] Detect revert (in-progress / sequence)
- [ ] Detect bisect (good / bad / current)
- [ ] Detect `git am` (in-progress)
- [ ] Detect detached HEAD
- [ ] Surface each as a distinct glyph + a11y label

### 24.2 Working tree
- [ ] Counts: staged / unstaged / untracked / conflict files
- [ ] Stash count
- [ ] Sparse-checkout active flag (cone vs non-cone)
- [ ] Submodule dirty/behind/ahead aggregation
- [ ] LFS active + pointer-only files

### 24.3 Branch state
- [ ] Ahead/behind upstream counts (async)
- [ ] Last fetch age (warn if > N hours)
- [ ] HEAD signed-commit state (gpg/ssh)
- [ ] Branch protection hint (read remote rules, cached)

### 24.4 Mirroring for jj / sapling / hg
- [ ] Map each git state to its native concept
- [ ] Document the mapping in `docs/vcs/state-mapping.md`
- [ ] Snapshot tests per VCS

### 24.5 Performance
- [ ] Use libgit2 bindings via Zig FFI (avoid spawning git)
- [ ] Benchmark all states on a 1M-commit repo
- [ ] Document fallback to spawning when libgit2 missing

## Phase 25 — Feedback + community

### 25.1 `shisa report`
- [ ] CLI: capture config (redacted) + logs (last 1MB) + bench results
- [ ] Output a single .tar.gz the user inspects before sharing
- [ ] Document what's in the bundle
- [ ] CI test: redaction rules actually scrub the documented patterns

### 25.2 Community channels
- [ ] Set up Discord (low-friction) + Matrix mirror (privacy-friendly)
- [ ] GH Discussions for long-form
- [ ] Monthly office hours (recorded; captioned)
- [ ] First-response SLA: 7 days

### 25.3 Triage cadence
- [ ] Weekly triage meeting (15 min, recorded)
- [ ] Labels: kind (bug/perf/feat), area (core/cloud/ai/vcs/...), priority
- [ ] Public board mirroring labels

### 25.4 Sponsor channels
- [ ] GH Sponsors set up
- [ ] Open Collective with public ledger
- [ ] `FUNDING.md` explains where money goes
- [ ] Sponsor recognition policy (no feature demands)

## Phase 26 — Daemon lifecycle hardening

### 26.1 Supervisor
- [ ] Standalone `shisa-supervisor` binary (~200 KiB)
- [ ] Exponential-backoff restart with cap
- [ ] Heartbeat protocol (1 s interval)
- [ ] Auto-disable supervisor if it itself crashes
- [ ] Document install path (launchd plist on macOS, systemd --user unit on Linux)

### 26.2 Auto-spawn
- [ ] `shisa prompt --auto-spawn` forks `shisad` on missing socket
- [ ] 100 ms grace period; fallback to sync if not ready
- [ ] Single-instance `flock` enforcement
- [ ] Race-tested

### 26.3 Graceful shutdown
- [ ] `SIGTERM` drains in 5 s, unlinks socket
- [ ] `SIGUSR1` reload
- [ ] `SIGUSR2` stack dump
- [ ] Tests for each signal handler

### 26.4 Health + metrics
- [ ] `shisad --health` exit-0/exit-1
- [ ] `shisad --metrics` JSON (cache stats, render histogram, plugins)
- [ ] Optional Prometheus exporter (off by default)

### 26.5 Self-update
- [ ] `shisa update` checks GH Releases (only network call; opt-in by default)
- [ ] Sigstore signature verification
- [ ] Atomic swap on success; rollback on failure

## Phase 27 — Cache architecture hardening

### 27.1 L1 rendered-prompt LRU
- [ ] Implement bounded LRU keyed by render-input tuple
- [ ] Lock-free reads where possible
- [ ] Hit-rate metric exposed via `--metrics`

### 27.2 L2 module-output cache
- [ ] Persist optionally to `~/.cache/shisa/cache.bin`
- [ ] Versioned schema with migration
- [ ] Cold-start hydration with checksum verification

### 27.3 L3 external-command cache
- [ ] Keyed on `(cmd, args, cwd, mtime-set-of-watched-paths)`
- [ ] Negative caching for missing tools
- [ ] Configurable per-module TTL

### 27.4 Invalidation
- [ ] fsnotify integration with declared watch paths
- [ ] Debounce events (configurable, default 50 ms)
- [ ] Monotonic `cache_rev` propagated to L1 keys
- [ ] Manual: `shisa cache clear [--module=foo]`

### 27.5 Stress tests
- [ ] 10k cd loops with cache hit-rate measured
- [ ] Cache thrash scenario (constantly invalidated)
- [ ] Memory ceiling under high-churn

## Phase 28 — Async / redraw mechanism (per-shell)

### 28.1 Zsh
- [ ] Self-pipe FD wired to `zle reset-prompt`
- [ ] Test in tmux + plain zsh + alacritty + iTerm
- [ ] Document `RPS1` interaction

### 28.2 Bash
- [ ] `bind -x` + escape sequence redraw trick
- [ ] Document Bash 4+ requirement
- [ ] Graceful sync fallback on older bash

### 28.3 Fish
- [ ] `commandline -f repaint` after async fill
- [ ] Compatibility with fish-async-prompt mechanism without depending on it

### 28.4 Nushell
- [ ] Custom event hook for re-prompt
- [ ] Document supported nu versions

### 28.5 PowerShell
- [ ] `Register-EngineEvent` async-fill where supported
- [ ] Graceful degradation matrix in docs

### 28.6 Integration tests
- [ ] expect/pexpect scenarios per shell
- [ ] Verify async fill arrives within N ms
- [ ] Verify transient prompt shrinks history

## Phase 29 — Lua plugin SDK hardening

### 29.1 Lua VM selection
- [ ] Benchmark Lua 5.4 vs LuaJIT on plugin hot paths
- [ ] Pick winner based on sandbox safety + perf
- [ ] Document decision

### 29.2 Stripped stdlib
- [ ] Remove `os.execute`, `os.exit`, `os.remove`, `os.rename`, `io.popen`, `io.open`, `loadfile`, `dofile`, `package.loadlib`, most of `debug.*`
- [ ] Whitelist `require` to project-local files only
- [ ] Snapshot tests asserting removed globals are nil

### 29.3 Capability gate
- [ ] Implement manifest parsing + validation
- [ ] Daemon-side check on every API call
- [ ] Reject runtime calls without declared capability
- [ ] Re-prompt on capability upgrade

### 29.4 Resource limits
- [ ] Memory: 16 MiB hard cap per plugin (instrumented allocator)
- [ ] CPU: 1 ms wall budget, 5 ms hard kill in debug
- [ ] Three-strikes-disabled rule for slow plugins
- [ ] Plugin status visible via `shisa plugin list`

### 29.5 Bridge fuzz
- [ ] Fuzz every `ctx:*` function for input handling
- [ ] OSS-Fuzz integration
- [ ] Bug-bounty pool for sandbox escapes

### 29.6 Plugin lifecycle
- [ ] `on_load`, `render`, `update`, `pre_exec`, `on_unload` contracts
- [ ] Tests for each hook
- [ ] Document max-allowed wall time per hook

### 29.7 Plugin tooling
- [ ] `shisa plugin new <name>` scaffolds a starter plugin
- [ ] `shisa plugin lint <path>` validates manifest + best practices
- [ ] `shisa plugin pack <path>` produces a signed `.shisa-plugin` bundle
- [ ] Sample plugin template repo

## Phase 30 — Theme & rendering engine

### 30.1 Color model
- [ ] Implement Oklab + Oklch parsing
- [ ] Downcast to truecolor / 256 / 16 / none
- [ ] Tests against established Oklab reference values

### 30.2 Theme loader
- [ ] Parse TOML themes (`okiya-night.toml`)
- [ ] Resolve palette references (`@accent`)
- [ ] Validate (`shisa theme validate`)
- [ ] Generate preview screenshots in CI

### 30.3 Built-in themes
- [ ] okiya-night (signature dark)
- [ ] okiya-day (matching light)
- [ ] gruvbox-rainbow (familiar)
- [ ] tokyo-night (familiar)
- [ ] nord-dark (familiar)
- [ ] plain (zero-color baseline)
- [ ] a11y (WCAG AAA, ASCII)

### 30.4 Multi-line layout
- [ ] Implement `[layout]` parser
- [ ] Filler segment width calc
- [ ] Right-aligned segments per line
- [ ] Snapshot tests for each layout shape

### 30.5 Glyph fallback
- [ ] Glyph tier resolver (nerdfont → unicode → ascii)
- [ ] Validator enforces fallback declarations
- [ ] `shisa font check` rendering probe
- [ ] Documented NerdFont version requirements per theme

### 30.6 Live preview
- [ ] `shisa theme preview <theme>` renders a sample prompt with stub state
- [ ] `shisa theme gallery` opens the gallery in a browser (no telemetry)
- [ ] Web preview at shisa.sh/themes (no JS framework; static)

## Phase 31 — Security threat model + audits

### 31.1 Threat model doc
- [ ] Maintain `docs/threat-model.md` per §32
- [ ] Annual review (calendar entry)
- [ ] Update with each new pack

### 31.2 Fuzz nightly
- [ ] Frame deframer
- [ ] JSON request decoder
- [ ] Lua bridge surface
- [ ] Redaction rules
- [ ] Failure crashes uploaded to private bucket

### 31.3 Bug bounty
- [ ] Define scope (sandbox escapes, IPC spoofing, supply chain)
- [ ] Pool funded by Open Collective (publicly tracked)
- [ ] Public hall of fame for valid reports

### 31.4 Pre-1.0 audit
- [ ] Engage an external security firm
- [ ] Publish findings + remediation
- [ ] Roadmap to address residual risk

### 31.5 Annual re-audits
- [ ] Calendar entry + budget allocation
- [ ] Audit findings published as advisory
- [ ] Trust score visible on shisa.sh/security

## Phase 32 — Advanced testing infrastructure

### 32.1 Snapshot tests
- [ ] All built-in themes × glyph caps × color caps
- [ ] Prompt fixtures: clean, dirty git, conflict, prod, etc.
- [ ] Update tool with explicit confirm gate (no auto-write)

### 32.2 Property tests
- [ ] Wire protocol roundtrip
- [ ] Theme renders survive arbitrary state
- [ ] Cache eviction invariants

### 32.3 Integration tests via expect/pexpect
- [ ] Per-shell session scripts
- [ ] Verify hooks, redraw, transient prompt
- [ ] Verify pre_exec blocking and bypass

### 32.4 E2E in Docker
- [ ] Full-OS images for each supported distro
- [ ] Run shells inside container; assert prompt output
- [ ] Matrix of `shell × distro × version`

### 32.5 Hardware-perf bench
- [ ] Monthly run on a documented baseline machine
- [ ] Publish to shisa.sh/bench
- [ ] Compare to starship + p10k + oh-my-posh in same run

### 32.6 Mutation testing
- [ ] Apply mutation testing to core logic
- [ ] Mutation-survival score tracked over time

## Phase 33 — Internationalization implementation

### 33.1 Strings extraction
- [ ] Tool to extract user-facing strings to `i18n/en-US.po`
- [ ] CI gate: every PR touching user-facing text updates the catalog

### 33.2 Locale routing
- [ ] Detect `LANG` / `LC_*` env
- [ ] `shisa config set locale=...` override
- [ ] Fall through to en-US for missing translations

### 33.3 RTL rendering
- [ ] Bidi detection
- [ ] Optional segment reversal
- [ ] Tested with Arabic, Hebrew, Persian fixture strings

### 33.4 CJK width
- [ ] UAX-11 East Asian Width table
- [ ] Width-aware segment truncation
- [ ] Tested with Chinese, Japanese, Korean fixtures

### 33.5 Translator onboarding
- [ ] Weblate or equivalent set up
- [ ] Document the workflow
- [ ] Translator credits page

## Phase 34 — v2 RFC preparation

Opened 30 days post v1.0. Pre-work tasks below.

- [ ] Track "v2 candidate" issues with a label
- [ ] Collect v2 candidates from quarterly retros
- [ ] Native Windows POC: ReadDirectoryChangesW prototype
- [ ] Persistent daemon via launchd / systemd unit prototype
- [ ] age + git-remote dotfile sync prototype
- [ ] Per-project config layering RFC draft
- [ ] Marketplace 2.0 RFC draft

## Continuous extensions (additions)

- [ ] Reproducibility check on every tagged release
- [ ] SBOM diff review on every tagged release
- [ ] Re-run threat-model annually with calendar reminder
- [ ] A11y audit calendar reminder
- [ ] Update `VOUCHES` whenever a contributor is granted write access
- [ ] Each merged RFC produces a `docs/internals/` page summarizing the decision
- [ ] Each pack tracks its own pack-perf budget; regressions blocked at PR time
- [ ] Each shell-version drop documented in compatibility matrix
- [ ] `shisa doctor` updated whenever a new failure mode is added
- [ ] Every new module ships with a benchmark + an a11y label + a glyph fallback
