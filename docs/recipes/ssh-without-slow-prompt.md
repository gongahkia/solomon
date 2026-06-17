# Running Shisa over SSH Without Slowing the Prompt

Run the daemon on the remote host and keep the shell hook pointed at a local Unix socket on that host.

## 1. Use a remote-local socket

On Linux, Shisa uses:

```text
$XDG_RUNTIME_DIR/shisa.sock
```

When `XDG_RUNTIME_DIR` is unset, it falls back to:

```text
/run/user/<uid>/shisa.sock
```

Do not point `SHISA_SOCKET` at a network filesystem path.

## 2. Start the daemon on the remote host

For a smoke run:

```sh
./zig-out/bin/shisad --foreground
```

In another SSH session:

```sh
./zig-out/bin/shisa doctor
```

For regular use, run `shisad` from a user service on the remote host.

## 3. Use an SSH-focused module list

Keep remote prompts small:

```toml
version = 1
theme = "plain"

[prompt]
modules = ["cwd", "git_branch", "exit_status", "jobs", "cmd_duration", "user_host", "ssh_target"]

[modules.user_host]
mode = "ssh"
```

`git_branch` is async. `ssh_target` is sync and only renders when `SSH_CONNECTION` is non-empty.

## 4. Source the shell hook remotely

```sh
export SHISA_BIN=/path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.zsh
```

For fish, the init file enables instant prompt by default:

```fish
set -gx SHISA_BIN /path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.fish
```

zsh and bash hooks use a fallback prompt when the daemon socket is missing. Their CLI path supports `--instant`, but the hooks do not enable it by default.

## 5. Verify inside SSH

```sh
shisa explain
```

Confirm `ssh_target` is in the pipeline. During an SSH session, it renders the remote host and risk tier from `SSH_CONNECTION`.

For async debugging:

```sh
shisa prompt --shell zsh --cwd "$PWD" --no-async
```

See [SSH Target](../ssh-target.md), [Socket Paths](../socket-paths.md), [Shells](../shells.md), and [Architecture](../architecture.md).
