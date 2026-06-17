# Migrating from Powerlevel10k Step-by-Step

Use `shisa import-p10k` to translate Powerlevel10k prompt element lists into a Shisa module pipeline.

## 1. Generate Shisa config

Run the importer from the Shisa config directory so any migration notes land next to the generated config:

```sh
mkdir -p ~/.config/shisa
cd ~/.config/shisa
shisa import-p10k ~/.p10k.zsh > shisa.toml
```

For a dry run, write somewhere else first:

```sh
shisa import-p10k ~/.p10k.zsh > /tmp/shisa.p10k.toml
```

## 2. Read the generated comments

The output keeps source layout context as comments:

```toml
# Powerlevel10k left elements: dir, vcs, status
# Powerlevel10k right elements: aws, kubecontext, time
```

Unsupported elements are emitted in the config and, when present, written to `migration-notes.md` in the current directory.

## 3. Check mapped modules

Common mappings:

| Powerlevel10k | Shisa |
| --- | --- |
| `dir` | `cwd` |
| `vcs` | `git_branch` |
| `status` | `exit_status` |
| `command_execution_time` | `cmd_duration` |
| `background_jobs` | `jobs` |
| `context` | `user_host` |
| `aws`, `gcloud`, `azure`, `kubecontext` | `cloud_ctx` |
| `virtualenv`, `nodeenv`, `go_version`, `rust_version` | `language_versions` |
| `time` | `time` |

Open [Powerlevel10k Module Map](../powerlevel10k-module-map.md) for the full support table.

## 4. Handle instant prompt

The importer comments the source setting and the Shisa env value:

```toml
# Powerlevel10k instant_prompt: quiet
# Shisa instant prompt: SHISA_INSTANT=1
```

`SHISA_INSTANT` is honored by fish, nushell, and PowerShell init files. zsh and bash hooks currently leave instant prompt off by default; their CLI path supports `--instant`.

## 5. Switch shell startup

Remove the Powerlevel10k source lines after the Shisa hook is in place:

```sh
export SHISA_BIN=/path/to/shisa/zig-out/bin/shisa
source /path/to/shisa/init/shisa.zsh
```

Run:

```sh
shisa explain
```

Confirm the module list matches the generated `[prompt].modules`.

See [Quickstart](../quickstart.md), [Shells](../shells.md), and [Config Schema](../config-schema.md).
