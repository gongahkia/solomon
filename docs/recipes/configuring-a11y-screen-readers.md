# Configuring `--a11y` for Screen Readers

Use `SHISA_A11Y=1` for interactive hooks, or `shisa prompt --a11y` for one-shot checks.

## 1. Start the daemon

```sh
./zig-out/bin/shisad --foreground
```

Keep that session running, then use another shell for the prompt hook.

## 2. Enable a11y mode before sourcing the hook

zsh:

```sh
export SHISA_A11Y=1
export SHISA_BIN=/path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.zsh
```

bash:

```sh
export SHISA_A11Y=1
export SHISA_BIN=/path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.bash
```

fish:

```fish
set -gx SHISA_A11Y 1
set -gx SHISA_BIN /path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.fish
```

nushell:

```nu
$env.SHISA_A11Y = "1"
$env.SHISA_BIN = "/path/to/shisa/zig-out/bin/shisa"
source /path/to/shisa/init/shisa.nu
```

PowerShell:

```powershell
$env:SHISA_A11Y = "1"
$env:SHISA_BIN = "/path/to/shisa/zig-out/bin/shisa"
. /path/to/shisa/init/shisa.ps1
```

## 3. Verify the one-shot path

```sh
./zig-out/bin/shisa prompt --a11y --shell zsh --cwd "$PWD" --no-async
```

`--a11y` requests `color_caps = "none"` and `glyph_caps = "ascii"`, strips ANSI control sequences from the returned prompt, and normalizes known prompt glyphs to ASCII.

## 4. Keep risk visible in text

Use modules that already render text labels:

```toml
version = 1
theme = "plain"

[prompt]
modules = ["cwd", "git_branch", "exit_status", "jobs", "cmd_duration", "cloud_ctx", "ssh_target"]
```

`exit_status` renders `exit:<code>`. `ssh_target` renders the host and tier text, for example `-> prod-bastion (prod)`. `cloud_ctx` renders provider labels such as `aws`, `gcp`, `az`, and `k8s`.

Current scope: `SHISA_A11Y=1` configures prompt rendering. `shisa init --a11y` and an alt-text dump command are separate accessibility-roadmap items.

See [Shells](../shells.md), [SSH Target](../ssh-target.md), [Risk Tiers](../risk-tiers.md), and [Config Schema](../config-schema.md).
