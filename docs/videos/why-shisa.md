# Why Shisa

Purpose: 3-minute project intro for developers who already use Starship, Powerlevel10k, Tide, Oh My Posh, or a custom shell prompt and care about prompt latency.

Target length: 2:55 to 3:05.

## Message

Shisa is a daemon-backed, async-first, cross-shell prompt. It keeps slow context work out of the interactive shell by moving it into a per-user daemon with caches, filesystem invalidation, async probes, and shell fallbacks.

## Audience

- Developers who work in large repos.
- Developers who use multiple shells across local, remote, and container sessions.
- Developers who need cloud, VCS, language, and safety context in the prompt without adding prompt lag.

## Structure

| Time | Visual | Voiceover |
| --- | --- | --- |
| 0:00-0:15 | Terminal prompt in a large repo, then a slow prompt spinner or pause. | "A shell prompt is supposed to disappear into muscle memory. But in large repos, cloud-heavy setups, or plugin-heavy prompts, the prompt itself can become the thing that interrupts you." |
| 0:15-0:35 | Split view: shell hook on left, daemon diagram on right. | "Shisa's bet is simple: the shell should stay tiny. Capture cwd, exit status, jobs, duration, and terminal capability hints. Send them to a local daemon. Print the response or a fallback." |
| 0:35-0:55 | Show `docs/assets/quickstart.gif` or equivalent terminal recording. | "The daemon owns the expensive work: VCS state, language version probes, cloud context, cache invalidation, and async refresh. The prompt path stays focused on returning a string quickly." |
| 0:55-1:20 | Architecture bullets: daemon, socket, renderer, async modules, cache, fsnotify. | "Modules are classified as sync, async, or cached. Sync modules must be bounded. Async modules return a placeholder and fill later. Cached modules read daemon-maintained state." |
| 1:20-1:45 | Demo `shisa explain`, then render with pending git/language segments. | "That lets Shisa show useful context without making every prompt pay the worst-case cost of `git status`, language version commands, or local cloud config reads." |
| 1:45-2:05 | Show shell fallback behavior with daemon unavailable. | "If the daemon is missing or unreachable, the hook still prints a minimal prompt. The shell remains the owner of interactivity." |
| 2:05-2:25 | Show plugin manifest with capabilities. | "Plugins are Lua, but host access is capability-gated. Filesystem, exec, env, secrets, pre-exec, and network access must be declared and reviewed." |
| 2:25-2:45 | Show docs pages: profiling, cache architecture, threat model. | "The project is built around measurable constraints: warm render p99 under 2 ms, fallback under 5 ms, no core telemetry, and no network calls in the core prompt path." |
| 2:45-3:00 | End card: repo, quickstart command, docs. | "Shisa is for people who want a prompt with modern context, but still want the command line to feel immediate. Start with the quickstart, then run the benchmark on your own repos." |

## Transcript

A shell prompt is supposed to disappear into muscle memory.

But in large repos, cloud-heavy setups, or plugin-heavy prompts, the prompt itself can become the thing that interrupts you.

Shisa's bet is simple: the shell should stay tiny.

Capture the current directory, exit status, background jobs, last command duration, and terminal capability hints. Send that to a local daemon. Print the response, or print a fallback if the daemon is unavailable.

The daemon owns the expensive work: VCS state, language version probes, cloud context, cache invalidation, async refresh, and plugin boundaries.

The prompt path stays focused on returning a string quickly.

Modules are classified as sync, async, or cached.

Sync modules must be bounded. Async modules return a placeholder and fill later. Cached modules read daemon-maintained state.

That means Shisa can show useful context without making every prompt pay the worst-case cost of `git status`, language version commands, or local cloud config reads.

If the daemon is missing or unreachable, the hook still prints a minimal prompt. The shell remains the owner of interactivity.

Plugins are Lua, but host access is capability-gated.

Filesystem, exec, environment, secrets, pre-exec, and network access must be declared and reviewed before plugin behavior crosses into the host.

The project is built around measurable constraints: warm render p99 under 2 ms, fallback under 5 ms, no core telemetry, and no network calls in the core prompt path.

Shisa is for people who want a prompt with modern context, but still want the command line to feel immediate.

Start with the quickstart, then run the benchmark on your own repos.

## Recording Checklist

- Build release binaries: `zig build release`.
- Open with the slow-prompt problem; do not spend more than 15 seconds on competitors.
- Use a readable terminal font at 120 columns or fewer.
- Record `shisa explain` to show module order.
- Record one render path with async placeholders.
- Record one daemon-unavailable fallback.
- Show `docs/profiling.md`, `docs/cache-architecture.md`, and `docs/threat-model.md`.
- End on quickstart, benchmark, and local-only privacy points.

## Cut List

- Remove any claim that a released package exists before release engineering lands.
- Remove benchmark numbers not produced in the recording session.
- Remove cloud-provider names unless the demo uses local cached config only.
- Keep comparisons to other prompts brief and structural.
