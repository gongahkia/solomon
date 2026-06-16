# Migrate From Starship

## 1. Export current config

Starship usually reads:

```sh
~/.config/starship.toml
```

If you use `STARSHIP_CONFIG`, pass that path instead.

## 2. Generate Shisa config

```sh
shisa import-starship ~/.config/starship.toml > /tmp/shisa.toml
```

Review unsupported module comments:

```sh
grep 'Unsupported Starship modules' /tmp/shisa.toml
```

## 3. Install config

```sh
mkdir -p ~/.config/shisa
cp /tmp/shisa.toml ~/.config/shisa/shisa.toml
```

## 4. Install shell hook

Source the matching hook from your shell config:

```sh
source /path/to/shisa/init/shisa.zsh
source /path/to/shisa/init/shisa.bash
source /path/to/shisa/init/shisa.fish
source /path/to/shisa/init/shisa.nu
. /path/to/shisa/init/shisa.ps1
```

Use only the line for your shell.

## 5. Start daemon

```sh
shisad --foreground
```

For normal use, run `shisad` under your user service manager.

## Mapping Notes

- Starship `directory` maps to Shisa `cwd`.
- Starship git modules collapse into Shisa `git_branch`.
- Starship `python`, `nodejs`, `rust`, and `golang` map to `language_versions`.
- Starship cloud/container modules are not imported into core. Use Lua plugins or future plugin packs.
- Starship `custom` modules are not imported. Recreate them as capability-gated Lua plugins.

Full map: `docs/starship-module-map.md`.

## Verify

```sh
shisa explain
zig build test
```

`shisa explain` prints the resolved module pipeline. `zig build test` is only needed when hacking on Shisa itself.
