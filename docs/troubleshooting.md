# Troubleshooting

Start with:

```sh
shisa doctor
shisa doctor --lint
shisa doctor --lint --json
```

Use `--socket <path>` when testing an isolated daemon.

## Expected States

| Symptom | Meaning | Action |
| --- | --- | --- |
| `shisad: another daemon already owns the socket lock` | A daemon already owns that socket. | Reuse it, or pass a different `--socket`. |
| `[pending:git_branch]` or `[pending:<module>]` | First async render returned before the daemon cache filled. | Render again; this is normal. |
| `vpn:Tailscale` or another `vpn:<name>` segment | `vpn_status` is enabled and a VPN is active. | Remove `"vpn_status"` from `[prompt].modules` to hide it. |
| `skip pure import smoke` | Pure fixture paths were not provided. | Set `SHISA_PURE_ZSH_DIR` and `SHISA_PURE_FISH_DIR` only when testing Pure import. |
| `skip nix-shell language integration` | `nix-shell` is not installed. | Install Nix only if you need that integration test. |

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
