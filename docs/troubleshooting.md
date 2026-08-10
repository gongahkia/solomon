# Troubleshooting

Start with:

```sh
shisa doctor
shisa doctor --json --severity-min warning
shisa doctor --list-checks
```

Use `--socket <path>` when testing an isolated daemon.

For a shareable local bundle:

```sh
shisa doctor --report /tmp/shisa-doctor.json --json --severity-min info
```

## Expected States

| Symptom | Meaning | Action |
| --- | --- | --- |
| `shisad: another daemon already owns the socket lock` | A daemon already owns that socket. | Reuse it, or pass a different `--socket`. |
| `[pending:git_branch]` or `[pending:<module>]` | First async render returned before the daemon cache filled. | Render again; this is normal. |
| `vpn:Tailscale` or another `vpn:<name>` segment | `vpn_status` is enabled and a VPN is active. | Remove `"vpn_status"` from `[prompt].modules` to hide it. |
| `skip pure import smoke` | Pure fixture paths were not provided. | Set `SHISA_PURE_ZSH_DIR` and `SHISA_PURE_FISH_DIR` only when testing Pure import. |
| `skip nix-shell language integration` | `nix-shell` is not installed. | Install Nix only if you need that integration test. |
| `config_dir_permissions: wrong (755)` | Config dir is readable by more users than expected. | Run `shisa doctor --fix` or `chmod 0700 ~/.config/shisa`. |
| `shell_hook: missing` | Current shell startup file has no active shisa hook. | Run init with `--write-hook`, then restart the shell. |
| `SHISA_SOCKET differs` | Hook and CLI are targeting different sockets. | Unset `SHISA_SOCKET` or pass the same `--socket` to `shisa` and `shisad`. |

## Daemon And Socket

One daemon should own one socket.

```sh
shisa doctor
shisad --foreground &
```

Restart the default daemon:

```sh
pkill shisad
shisad --foreground &
```

Run an isolated daemon:

```sh
shisad --foreground --socket /tmp/shisa.sock &
shisa prompt --socket /tmp/shisa.sock --shell zsh --cwd "$PWD"
```

If the shell uses `SHISA_SOCKET`, pass the same path to both `shisa` and `shisad`.

On Unix, Shisa recreates its socket with mode `0600`. If `shisa doctor --only daemon/socket-permissions`
reports a different mode, restart `shisad` rather than broadening access to the socket.

Check only daemon state:

```sh
shisa doctor --only daemon/not-running,daemon/stale-socket,daemon/socket-mismatch
```

## Shell Hook

Install or refresh the hook:

```sh
shisa init --defaults --shell zsh --theme nord-dark --async on --write-hook
exec zsh
```

Check the active hook:

```sh
shisa doctor
echo "$SHISA_BIN"
echo "$SHISA_SOCKET"
```

`SHISA_BIN` must point to an executable `shisa` binary.

Duplicate hook blocks are reported as `shell/hook-duplicates`. Remove older `# >>> shisa >>>` blocks and rerun:

```sh
shisa init --defaults --write-hook
```

## Prompt Output

For a one-off render:

```sh
shisa prompt --shell zsh --cwd "$PWD"
```

For a traced render:

```sh
SHISA_DEBUG=1 shisa prompt --shell zsh --cwd "$PWD" 2>/tmp/shisa-debug.log
```

For glyph issues:

```sh
shisa font check
SHISA_GLYPH_CAPS=ascii shisa prompt --shell zsh --cwd "$PWD"
```

For host-specific prompt content during tests:

```sh
shisa doctor --only modules/vpn-active,prompt/async-pending --severity-min info
```

## Tests

Local smoke:

```sh
zig build debug
test/integration/first_run_smoke.sh
```

Full local suite:

```sh
zig build test
zig build release
zig build bench
```

If `zig build test` fails with host-specific prompt content, run `shisa doctor --lint --severity-min info` and check active modules such as `vpn_status`.

## Install And PATH

Check build/runtime binaries:

```sh
zig build release
shisa doctor --only install/zig-version,install/binary-set,install/path-shadowing --severity-min info
```

`install/path-shadowing` means the shell may run a different `shisa` than the one you just built.
