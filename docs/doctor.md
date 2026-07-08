# Doctor

`shisa doctor` is the first command to run when onboarding, debugging a prompt, or collecting support data. It is local-only by default.

```sh
shisa doctor
shisa doctor --json --severity-min error
shisa doctor --list-checks
```

## Modes

| Command | Use |
| --- | --- |
| `shisa doctor` | Human diagnostics, expected-state hints, and fixable issues. |
| `shisa doctor --lint` | Stable text findings for scripts. |
| `shisa doctor --json` | Machine-readable findings; implies `--lint`. |
| `shisa doctor --list-checks` | List check ids, categories, local/online mode, and docs links. |
| `shisa doctor --only id[,id]` | Run only selected checks. |
| `shisa doctor --skip id[,id]` | Skip selected checks. |
| `shisa doctor --online` | Add explicit network/release checks. |
| `shisa doctor --report path.json` | Write a redacted JSON report with doctor output, check registry, config, log tail, and daemon metrics. |
| `shisa doctor --fix [--yes]` | Apply only guarded local fixes. |

Use `--socket <path>` for isolated daemons:

```sh
shisa doctor --socket /tmp/shisa.sock
```

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | No findings at the selected severity, or non-lint human mode completed. |
| `1` | Findings were reported in lint/JSON mode. |
| `2` | Doctor itself failed. |

## JSON Shape

```json
{
  "version": 1,
  "status": "findings",
  "severity_min": "warning",
  "online": false,
  "checks_run": 34,
  "summary": { "info": 2, "warning": 1, "error": 1 },
  "findings": [
    {
      "id": "daemon/not-running",
      "severity": "error",
      "category": "daemon",
      "message": "daemon is not reachable",
      "detail": null,
      "evidence": "socket-missing",
      "path": "/tmp/shisa.sock",
      "paths": ["/tmp/shisa.sock"],
      "command": "shisad --foreground &",
      "commands": ["shisad --foreground &"],
      "fix_hint": "start `shisad --foreground &` or run `shisa doctor --fix`",
      "fixable": true,
      "docs_url": "docs/troubleshooting.md#daemon-and-socket"
    }
  ],
  "count": 1
}
```

## Fixes

`--fix` can:

| Finding | Action |
| --- | --- |
| `shell/hook-missing` | Runs `shisa init --write-hook`. |
| `daemon/stale-socket` | Removes the socket only after owner checks report no owner. |
| `daemon/not-running` | Runs `shisad --daemonize --socket <path>`. |
| `config/dir-permissions` | Runs `chmod 0700 <config_dir>`. |
| `terminal/nerd-font` | Prints an install command only. |

## Check Map

| Id | Category | Signal |
| --- | --- | --- |
| `install/zig-version` | install | `zig version` differs from `build.zig.zon` or Zig is missing. |
| `install/binary-set` | install | `shisad` or `shisa-supervisor` is missing beside `shisa`. |
| `install/path-shadowing` | install | `which -a shisa` does not include the running binary. |
| `config/unreadable` | config | Config cannot be read. |
| `config/invalid` | config | Config parser rejects `shisa.toml`. |
| `config/dir-permissions` | config | Config directory mode is broader than `0700`. |
| `config/deprecations` | config | Config contains known deprecated keys. |
| `daemon/not-running` | daemon | Socket health check fails. |
| `daemon/stale-socket` | daemon | Socket exists but daemon does not respond. |
| `daemon/already-running` | daemon | Healthy daemon exists; starting another default daemon prints `AlreadyRunning`. |
| `daemon/socket-mismatch` | daemon | `SHISA_SOCKET` differs from the checked socket. |
| `daemon/non-default-socket` | daemon | Doctor is checking an isolated socket. |
| `daemon/protocol` | daemon | Version/protocol request fails or is malformed. |
| `daemon/metrics` | daemon | Metrics request fails or lacks render metrics. |
| `daemon/log-warnings` | daemon | Recent daemon log tail has warning entries. |
| `shell/hook-missing` | shell | Hook marker is absent from the detected shell startup file. |
| `shell/hook-duplicates` | shell | Startup file has multiple hook blocks. |
| `shell/bin-missing` | shell | `SHISA_BIN` is not executable. |
| `terminal/nerd-font` | terminal | Font override says Nerd Font support is missing. |
| `terminal/unknown` | terminal | Terminal detection cannot identify capabilities. |
| `prompt/async-pending` | prompt | Sample prompt contains `[pending:<module>]`. |
| `prompt/render-sample` | prompt | Sample daemon render succeeded. |
| `modules/vpn-active` | modules | `vpn_status` is enabled and active. |
| `modules/git` | modules | Git module is enabled in a Git repo but `git` is missing. |
| `modules/language-tools` | modules | Project markers exist but language tool binaries are missing. |
| `modules/cloud-cache` | modules | `cloud_ctx` is enabled with all providers disabled. |
| `plugins/runtime` | plugins | Lua runtime is unavailable. |
| `plugins/manifests` | plugins | Plugin directory names are invalid and ignored. |
| `platform/runtime-dir` | platform | Runtime/config directory signal is unusual for the OS. |
| `platform/fsnotify` | platform | Watcher backend is unsupported or Linux watch limit is low. |
| `performance/prompt-budget` | performance | Sample daemon render fails or exceeds 10 ms. |
| `security/permissions` | security | Config file or directory permissions are broader than expected. |
| `tests/optional-prereqs` | tests | Optional Pure/Nix integration prereqs are absent. |
| `release/packaging` | release | Release binaries are missing. |
| `release/online` | release | Explicit `--online` tag lookup fails or succeeds. |

## Reports

```sh
shisa doctor --report /tmp/shisa-doctor.json --json --severity-min info
```

The report is JSON, not an archive. It embeds redacted config and log tail using the same redaction rules as `shisa report`.

## Adding Failure Modes

Any new user-visible failure mode should update `shisa doctor` in the same change unless it cannot be detected locally.

Required review notes:

- symptom
- local signal
- finding id/category/severity
- fixability and safety gate
- test or reason detection cannot be tested
