# RFC-0014: Windows Native Transport

- Status: Draft
- Created: 2026-07-08
- Owner: core maintainers
- Area: Windows, daemon IPC, shell integration

## Summary

Defines the native Windows path for Shisa: per-user named-pipe IPC, SID-derived default pipe names, PowerShell hook support, Job Object supervisor containment, `ReadDirectoryChangesW` filesystem notifications, and console-control shutdown handling.

## Motivation

Windows users should not need WSL for a prompt whose shell integration is already PowerShell-aware. Native support also prevents the daemon lifecycle model from depending on Unix socket assumptions in code that is otherwise cross-platform.

## Design

Windows uses the same length-prefixed JSON frame as macOS/Linux, but transports it over a named pipe:

```text
\\.\pipe\shisa-<sid>
```

`<sid>` is the current user's Windows SID. The CLI computes it from the process token; tests may override with `SHISA_WINDOWS_SID`.

The implementation lands in phases:

- Phase 1: cross-compile all binaries, derive the default pipe path, make the client open named pipes, report `ReadDirectoryChangesW` as the fsnotify backend, install `SetConsoleCtrlHandler`, keep PowerShell rendering via fallback when the daemon is unavailable, and add `windows-2022` CI.
- Phase 2: replace the Windows daemon server stub with a synchronous named-pipe listener that serves render, health, metrics, reload, version, and preexec operations. `subscribe` returns a framed unsupported response until overlapped streaming is designed.
- Phase 3: expand Windows runtime e2e coverage beyond daemon startup, prompt render, health, doctor, and PowerShell hook path checks.

The supervisor creates daemon children suspended, assigns them to a Windows Job Object, then resumes the main thread.

## Performance

The frame format is unchanged. Named-pipe connection-per-request remains the baseline until runtime measurements show whether persistent connections are needed.

## Security

The pipe name includes the user SID to prevent accidental cross-user endpoint reuse. Pipe ACL hardening is still required before native Windows support leaves RFC status; default Windows named-pipe ACLs are not treated as the final security boundary.

## Compatibility

No protocol version bump. Unix socket behavior on macOS/Linux is unchanged. Windows PowerShell hooks keep rendering a sync fallback prompt if the named pipe is missing or unreachable.

## Rejected Alternatives

- **WSL-only support:** rejected. It leaves native PowerShell users on other prompt projects.
- **Username-derived pipe names:** rejected. Usernames are mutable and less precise than SIDs.
- **TCP localhost transport:** rejected. It adds firewall and spoofing surface for no current benefit.

## Unresolved Questions

- Final pipe security descriptor and ACL.
- Whether Windows subscribe streams need overlapped I/O before v1.x.
- How much of `test/e2e/` should run on `windows-2022` once the Phase 2 server lands.
