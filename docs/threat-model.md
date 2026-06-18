# Threat Model

This document covers the current Shisa architecture, theme/static-site surface, and plugin surface as of 2026-06-18.

## Assets

| Asset | Why it matters |
| --- | --- |
| Prompt output | Wrong context can cause commands to run in the wrong repo, cloud account, or SSH target. |
| Shell command stream | `preexec` data can expose sensitive command text. |
| Local files and env | Kubeconfigs, cloud profiles, `.env`, tokens, SSH config, and repo contents are sensitive. |
| Unix socket | The CLI and shell hooks trust daemon responses received over the per-user socket. |
| Plugin trust state | Capability changes decide which host APIs a plugin can use. |
| Theme files and previews | Theme TOML and generated/static preview HTML influence what users inspect before installing or copying themes. |
| Audit logs | `prod_guard` decisions need enough context for review without leaking secrets. |
| Release artifacts and docs | Users install binaries and follow docs produced by CI. |

## Trust Boundaries

| Boundary | Data crossing | Primary controls |
| --- | --- | --- |
| Shell hook to CLI | cwd, exit status, jobs, duration, shell name, optional command text | small CLI surface, fallback prompt, `SHISA_*` opt-ins |
| CLI to daemon | framed JSON over a Unix-domain socket | protocol validation, frame-size cap, per-user socket paths |
| Daemon to local host | filesystem, env, subprocesses, terminal metadata | core-only synchronous hot path, capability checks for plugins |
| Lua plugin to host API | declared manifest capabilities | deny-by-default manifest, strict loading, stripped Lua globals |
| Editor/subscriber to daemon | read-only topic streams | subscribe path rejects mutating and preexec messages |
| Theme/static preview to browser | generated HTML and local preview files | static HTML, no JavaScript framework, HTML escaping for generated gallery text |
| CI to release/docs | generated binaries, docs, checksums, Pages artifact | pinned workflow actions by major, build/test gates, release-tag workflow |

## STRIDE Summary

| Category | Threat | Current control | Residual risk |
| --- | --- | --- | --- |
| Spoofing | A process impersonates the daemon socket. | Socket path is per-user; `shisa doctor` reports socket and daemon status. | Same-user malware can still interfere with user-owned sockets. |
| Tampering | A plugin mutates host state through undeclared APIs. | Lua globals remove direct `os`, `io`, `package`, `require`, `dofile`, and `loadfile`; host API access must pass capability gates. | A LuaJIT sandbox escape remains a high-impact bug class. |
| Repudiation | A destructive prod command is denied or forced without traceability. | `prod_guard` appends decisions to `~/.local/state/shisa/prod_guard.jsonl`; `--force` logs `prod_guard_force`. | A user can edit local audit logs. They are local evidence, not tamper-proof records. |
| Information disclosure | A plugin reads local secrets or sends context off-host. | Missing `fs_read`, `env_read`, `secrets`, and `net` capabilities deny access. Install/trust flows surface declared capabilities. | User-approved broad scopes can still leak data. |
| Denial of service | Prompt rendering blocks shell input. | Slow work is daemon-side or async; shell hooks use fallback prompts when the daemon is unreachable. | Expensive core probes can still hurt daemon latency until profiled and cached. |
| Denial of service | Theme preview or static gallery generation consumes unbounded local resources. | Theme loader caps file reads at 1 MiB; built-in gallery generation uses a fixed theme list. | Large external theme previews may still be slow once inheritance and external packs expand. |
| Tampering | A theme name, glyph, or preview string injects active browser content into generated HTML. | `shisa theme gallery` escapes generated names/previews and emits local static HTML; checked-in `site/themes` has no scripts. | Manual static pages can drift from generated output until a dedicated site generator gate exists. |
| Elevation of privilege | A plugin uses `exec` or `pre_exec` to affect commands. | `exec` is an exact allow-list; `pre_exec` is a separate boolean capability and should be reserved for safety plugins. | If the user trusts a malicious plugin, Shisa cannot make that plugin benign. |

## Security Invariants

- Omitted capability fields deny access.
- Plugin install and strict mode reject malformed manifests before trust.
- Shell hooks must keep a local fallback prompt path when the daemon is unavailable.
- `prod_guard` is a safety interlock, not access control. Typing the tier or using `--force` can proceed.
- Subscribe/editor connections are read-only and must not run preexec or mutation paths.
- Network access is not part of the core prompt path.
- Release docs are built and published only from release tags matching `v*`.
- Generated theme gallery HTML must escape theme-controlled text and must not require client-side JavaScript.

## Phase 32 Verification Plan

Phase 32 test infrastructure is security evidence, not a replacement for review. As the advanced test suites are added, keep the threat model mapped to these checks:

| Surface | Required evidence |
| --- | --- |
| Wire protocol | Roundtrip and malformed-frame property tests for frame parsing and JSON request decoding. |
| Theme rendering | Snapshot matrix across built-in themes, glyph caps, color caps, and representative prompt states. |
| Cache state | Property tests for eviction, invalidation, and bounded storage behavior. |
| Shell hooks | Expect/pexpect sessions for prompt rendering, redraw, transient prompt, and preexec block/bypass paths. |
| Distro packaging | Docker E2E runs that exercise install, daemon startup, prompt rendering, and uninstall on supported distributions. |
| Fuzz findings | Nightly fuzz crashes must be retained with enough private detail to reproduce without publishing secrets. |

## Out of Scope

- Defending against a fully compromised user account.
- Preventing a user from editing their own shell hooks, config, trust file, or audit log.
- Hardening the terminal emulator itself.
- Treating local audit logs as forensic-grade immutable records.
- Claiming Lua sandbox isolation is equivalent to an OS sandbox.

## Review Checklist

- Does this change add a new trust boundary?
- Does it introduce filesystem, env, exec, network, secrets, or pre-exec access?
- Is the access denied by default?
- Is the capability narrow enough to explain in a plugin trust prompt?
- Can the prompt still render or fall back under daemon/plugin failure?
- Are protocol errors typed enough for clients to avoid parsing message text?
- Does any new audit output avoid secrets and command payload over-collection?
- Does a release/docs workflow change alter what users install or read?
- Does any new theme/static-site output escape HTML and avoid scripts, remote assets, and analytics?
- Does a Phase 32 test addition provide evidence for a named threat-model surface?

## References

- [Architecture](architecture.md)
- [Capabilities](capabilities.md)
- [Plugin API Reference](plugin-api.md)
- [Plugin Runtime](plugin-runtime.md)
- [Prod Guard](prod-guard.md)
- [Protocol Errors](protocol/errors.md)
- [RFC-0003 Lua Plugin Capability Manifest](../rfcs/0003-lua-plugin-capability-manifest.md)
- [RFC-0005 Wire Protocol v1](../rfcs/0005-wire-protocol-v1.md)
