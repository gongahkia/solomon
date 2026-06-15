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

---

# Plugin Packs — Phases 10+

These run in parallel to core hardening. Pack work **must not** regress core perf targets defined in north-star.md §10.

## Phase 10 — VCS moat pack (`shisa.vcs`)

### 10.1 Jujutsu (jj) — Tier 1
- [ ] Detect jj repos (`.jj/` directory)
- [ ] Read jj operation log via `jj op log --no-graph` (cached, fsnotify on `.jj/op_heads`)
- [ ] Show current change ID (short hash), description first line, divergence
- [ ] Show conflict state (`jj`'s first-class conflicts) inline
- [ ] Show working-copy commit vs. parent commits
- [ ] Async update on jj operations
- [ ] Snapshot tests against fixture jj repos
- [ ] Benchmark on a 10k-change jj repo

### 10.2 Sapling (sl) — Tier 1
- [ ] Detect sapling repos (`.sl/` directory)
- [ ] Read sapling state via `sl status --json` (cached, fsnotify on `.sl/store`)
- [ ] Show smartlog position (current commit in the stack)
- [ ] Show bookmark / branch
- [ ] Snapshot tests against fixture sapling repos

### 10.3 Mercurial (hg) — Tier 1
- [ ] Detect hg repos (`.hg/`)
- [ ] Read state via `hg summary --remote` (cached)
- [ ] Show branch, bookmark, topic (evolve), draft/public phase
- [ ] Handle mq queues if active

### 10.4 Stacked-diff awareness (`shisa.vcs.stack`)
- [ ] Detect Graphite (`gt`): `.graphite_repo_config`
- [ ] Detect ghstack: branch naming + `.ghstackrc`
- [ ] Detect spr / git-spr: `.git/refs/spr/`
- [ ] Detect `st`: meta files
- [ ] Detect git-spice (`gs`): meta files
- [ ] Detect git-town: `.git-town-branches.yml`
- [ ] Detect GitHub-native stacked PRs (`gh stack`) via remote config
- [ ] Render stack position (e.g., `2/5 ↑↓`)
- [ ] Add a `shisa stack` CLI to dump the detected stack as text

### 10.5 Worktree (`shisa.vcs.worktree`)
- [ ] Show `wt:<name>` when cwd is inside a worktree
- [ ] `shisa worktrees` CLI lists all worktrees, marks active
- [ ] Multi-worktree dirty-tree warning across worktrees

### 10.6 Community-tier plugins (templates only)
- [ ] Publish a Fossil plugin template
- [ ] Publish a Pijul plugin template
- [ ] Publish a Bazaar/Breezy plugin template
- [ ] Link to community repo in plugin marketplace

### 10.7 Tests & benches
- [ ] Per-VCS fixture corpus checked into `test/fixtures/vcs/<vcs>/`
- [ ] CI matrix runs each VCS module against fixtures on every PR
- [ ] Public benchmark vs. starship git on the same repos for parity confirmation

## Phase 11 — Cloud-safety pack (`shisa.cloud`)

### 11.1 Multi-cloud context segment (`cloud_ctx`)
- [ ] AWS profile from `AWS_PROFILE` env + `~/.aws/config` parse
- [ ] GCP project from `gcloud config config-helper --format=json` (cached, fsnotify on `~/.config/gcloud/`)
- [ ] Azure subscription from `az account show` (cached, fsnotify on `~/.azure/azureProfile.json`)
- [ ] Kubernetes context+namespace from kubeconfig (fsnotify on `KUBECONFIG`)
- [ ] Render unified segment with iconography per cloud
- [ ] Configurable show/hide per cloud
- [ ] Fast-path: never spawn subprocesses on the hot path; rely on cached file reads

### 11.2 Risk-tier classifier (`risk_tier`)
- [ ] Define regex defaults (`prod`, `production`, `live`, `*-prd-*` → prod; `stg`, `staging` → staging; `dev`, `sandbox` → dev)
- [ ] User-defined rules in `~/.config/shisa/risk_tiers.toml`
- [ ] Apply tier color to prompt's background bar (configurable)
- [ ] Per-cloud override (e.g., AWS profile=prod, k8s=dev → use max-tier=prod)
- [ ] `shisa cloud explain` CLI to print why a tier was chosen

### 11.3 Pre-exec prod guard (`prod_guard`)
- [ ] Implement pre-exec hook protocol across shells (zsh `preexec`, bash `DEBUG` trap, fish `fish_preexec`)
- [ ] Daemon-side classifier on command + tier
- [ ] Built-in destructive-pattern blocklist (kubectl delete/drain, terraform destroy, aws ec2 terminate, aws s3 rb, gcloud * delete, rm -rf, dd of=/dev/, mkfs, DROP TABLE)
- [ ] Typed-confirm UX (must type the tier name to proceed)
- [ ] `--force` bypass (logged)
- [ ] Audit log to `~/.local/state/shisa/prod_guard.jsonl`
- [ ] Bypass-log review CLI (`shisa cloud audit`)
- [ ] Fuzz the classifier against a corpus of dangerous-looking-but-safe commands (`kubectl get`, `terraform plan`)

### 11.4 IAM whoami (`iam_whoami`)
- [ ] AWS STS GetCallerIdentity cached value
- [ ] GCP `gcloud auth list` cached
- [ ] Azure `az account show` cached
- [ ] k8s `kubectl config current-context` user

### 11.5 SSO expiry (`sso_expiry`)
- [ ] AWS SSO: read `~/.aws/sso/cache/*.json`, find soonest `expiresAt`
- [ ] gcloud: parse `gcloud auth list --format=json` for expiry
- [ ] Azure: parse `~/.azure/accessTokens.json`
- [ ] HashiCorp Vault: read `~/.vault-token` lease info
- [ ] 1Password CLI: `op signin status` cache
- [ ] Render warning when any < 30 min remain (configurable)

### 11.6 IaC workspace (`iac_workspace`)
- [ ] Terraform: read `.terraform/environment` or current workspace from state
- [ ] Pulumi: read `Pulumi.<stack>.yaml` + active stack
- [ ] CDK: read `cdk.json` + `cdk.context.json`
- [ ] OpenTofu: same as Terraform
- [ ] Render workspace + lock indicator
- [ ] Pre-exec warn if workspace appears stale or remotely locked

### 11.7 Region drift (`region_drift`)
- [ ] AWS: compare `$AWS_REGION` / `$AWS_DEFAULT_REGION` to profile-configured region
- [ ] GCP: compare `$CLOUDSDK_COMPUTE_REGION` to gcloud config
- [ ] Azure: compare env vars to active subscription default
- [ ] Render warning segment when drift detected

### 11.8 Cost glance (`cost_glance`) — optional, heavy
- [ ] AWS Cost Explorer client (read-only, IAM least-priv guide)
- [ ] GCP Billing API client
- [ ] Azure Cost Management client
- [ ] Background hourly refresh in the daemon (off-thread)
- [ ] Cache to `~/.local/state/shisa/cost.json`
- [ ] Render compact MTD spend per cloud
- [ ] Document the IAM permissions required and the privacy implications (this calls cloud APIs!)

### 11.9 VPN status (`vpn_status`)
- [ ] Detect Wireguard interface up (parse `wg show`)
- [ ] Detect Tailscale (`tailscale status --json`)
- [ ] Detect NetBird, Cloudflare WARP, Zerotier
- [ ] macOS: detect OpenVPN / IKEv2 system VPN via `scutil`
- [ ] Linux: detect via NetworkManager d-bus
- [ ] Render compact "vpn:<name>" segment when active

### 11.10 SSH target (`ssh_target`)
- [ ] Detect inside SSH session via `$SSH_CONNECTION`
- [ ] Classify remote host using risk_tier rules
- [ ] Render `→ host (prod)` segment when remote

### 11.11 Container provenance (`container_provenance`)
- [ ] Detect docker (`/.dockerenv`)
- [ ] Detect podman (cgroups inspection)
- [ ] Detect devcontainer (`$REMOTE_CONTAINERS`)
- [ ] Detect nix-shell (`$IN_NIX_SHELL`)
- [ ] Detect distrobox / toolbx (env vars)
- [ ] Detect Kubernetes pod context (env vars / `/var/run/secrets/kubernetes.io/`)
- [ ] Render `[docker:web]` style segment

### 11.12 Tests & benches
- [ ] Mock cloud config fixtures under `test/fixtures/cloud/`
- [ ] Snapshot tests for each segment
- [ ] prod_guard fuzz suite
- [ ] Benchmark `cloud_ctx` cold path < 30ms, warm < 1ms
- [ ] Ship a `shisa cloud doctor` for self-diagnosis

## Phase 12 — AI plugin pack (`shisa.ai`)

### 12.1 Ollama integration
- [ ] Detect ollama install + running daemon
- [ ] Pull recommended small model (final choice TBD after benchmark: `qwen2.5:1.5b` / `gemma3:1b` / `phi3:mini`)
- [ ] Implement Ollama HTTP client in Zig
- [ ] Stream tokens with cancellation
- [ ] Benchmark first-token latency, tokens/sec, peak RAM
- [ ] Ship a `shisa ai bench` subcommand that reports local model perf

### 12.2 Next-command suggestion (`nextcmd`)
- [ ] Hotkey integration per shell (zsh widget, bash bind -x, fish key binding, nu / pwsh equivalents)
- [ ] Context builder: history slice + cwd + last command + last exit code
- [ ] Prompt template + few-shot examples checked into repo
- [ ] Inline preview UX (renders below the prompt line; ghost text)
- [ ] Accept (tab) / reject (esc) / next (alt-]) controls
- [ ] Bench: median round-trip < 800ms on a 2020 MacBook Air

### 12.3 Natural language to command (`nl2cmd`)
- [ ] Detect `?? ` prefix at start of input line
- [ ] Submit input to model with NL→cmd prompt template
- [ ] Render candidate command(s) with confidence
- [ ] Confirmation gate before exec (always; never auto-run)
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
- [ ] Document every plugin capability and its risk in `docs/capabilities.md`
- [ ] Maintain `docs/pack-status.md` showing incubation / graduated / vetted / EOL state per pack
- [ ] Triage pack issues at the pack repo level, not the core repo, once graduated
- [ ] Run the pack benchmark suite weekly on the main branch
