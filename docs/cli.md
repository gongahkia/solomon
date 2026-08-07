# CLI Reference

Generated from `shisa --help` with `zig build cli-docs`.

## `shisa`

```text
usage: shisa <command> [options]

commands:
  bench         benchmark prompt render via hyperfine
  cache         dump or clear cache state
  cloud         cloud helpers: audit, doctor, explain, preexec
  config        set persistent config values
  doctor        diagnose socket, config, plugins, lua, fsnotify
  explain       print resolved module pipeline
  font          render glyph fallback probes
  import-starship <path> [--dry-run|--diff] [--output PATH]
                translate starship.toml to shisa.toml
  import-p10k <path> [--dry-run|--diff] [--output PATH]
                translate .p10k.zsh to shisa.toml
  import-oh-my-posh <path> [--dry-run|--diff] [--output PATH]
                translate Oh My Posh JSON/YAML to shisa.toml
  import-tide <path> [--dry-run|--diff] [--output PATH]
                translate Tide fish settings to shisa.toml
  import-pure [--dry-run|--diff] [--output PATH]
                print the minimal Pure-compatible preset
  init          first-run wizard; --defaults writes without prompting
  pin           mark a path as never-evicted
  plugin        new, lint, doctor, verify, pack, install, list, enable, disable, or trust plugins
  prompt        render prompt through shisad; --right or --transient select variants
  render        alias for prompt; --explain-a11y dumps segment labels
  report        write a redacted support bundle .tar.gz
  supervisor    run shisad under a crash-restart supervisor
  theme         validate theme files
  trace         render once with module timing trace on stderr
  uninstall     remove shell hooks and optionally purge local state
  update        fetch, verify, and install a release artifact
  vouch         verify VOUCHES governance file

options:
  -h, --help    print help
      --version print version
```

## Command Help

### `shisa config`

```text
usage: shisa config set locale=<locale|auto>

commands:
  set locale=<locale|auto> set locale override; auto uses LC_ALL, LC_CTYPE, then LANG
```

### `shisa doctor`

```text
usage: shisa doctor [--socket PATH] [--fix [--yes]] [--lint] [--json] [--severity-min LEVEL]
                    [--list-checks] [--only IDS] [--skip IDS] [--online] [--report PATH]

options:
  --socket <path>        check a non-default daemon socket
  --fix                  apply available fixes interactively
  --yes, -y              apply fixes without prompting
  --lint                 read-only diagnostics with stable finding ids
  --json                 emit lint findings as JSON; implies --lint
  --severity-min LEVEL   info, warning, or error; default warning
  --list-checks          list doctor checks and exit
  --only IDS             comma-separated finding/check ids to run
  --skip IDS             comma-separated finding/check ids to skip
  --online               include explicit network/release checks
  --report PATH          write a redacted doctor report JSON
```

### `shisa font`

```text
usage: shisa font check

commands:
  check         render Nerd Font, Unicode, and ASCII glyph probes
```

### `shisa init`

```text
usage: shisa init [--defaults|--interactive] [--profile NAME] [--shell NAME] [--theme THEME] [--async on|off] [--write-hook]

options:
  --defaults      write default shisa.toml without prompting
  --interactive   force first-run wizard
  --profile NAME  write quiet (default), cloud, infra, or context-rich module defaults
  --shell NAME    target zsh, bash, fish, nu, or pwsh for hook install
  --theme THEME   write a built-in theme id
  --async on|off  enable or disable async fill in generated shell prefs
  --write-hook    append an idempotent shell hook block
  --a11y          write accessibility-first defaults
```

### `shisa report`

```text
usage: shisa report [--output path]

options:
  -o, --output <path> write bundle path; defaults to ./shisa-report-<timestamp>.tar.gz
```

### `shisa theme`

```text
usage: shisa theme <command> [args]

commands:
  validate <path>   validate a theme file
  preview <theme>   render a stub prompt from a built-in id or theme file
```

### `shisa trace`

```text
usage: shisa trace [--cwd DIR] [--exit N] [--jobs N]

options:
  --cwd DIR        render as if current directory is DIR
  --exit N         render with last exit code N
  --jobs N         render with running job count N
  --duration-ms N  render with command duration N
  --shell NAME     render for zsh, bash, fish, nu, or pwsh

trace output is written to stderr; prompt output remains on stdout.
```

### `shisa uninstall`

```text
usage: shisa uninstall [--shell NAME|--all-shells] [--restore-starship] [--purge --yes] [--dry-run]

options:
  --shell NAME        remove the hook from zsh, bash, fish, nu, or pwsh startup
  --all-shells        remove known shisa hook blocks from all supported startup files
  --restore-starship  add a Starship init line when the target startup file has none
  --purge             remove shisa config, cache, state, logs, socket, and lock files
  --yes               confirm --purge
  --dry-run           print planned removals without writing
```

### `shisa update`

```text
usage: shisa update [--verify|--no-verify] [--dry-run] [--rollback]

options:
  --verify             verify release signature before applying (default)
  --no-verify          skip cosign verification
  --dry-run            print update plan without downloading artifacts
  --rollback           restore shisa.previous over the current binary
  --repo OWNER/REPO    GitHub repo; default gongahkia/shisa
  --tag TAG            install an explicit release tag instead of latest
  --install-dir DIR    install directory; default current binary directory
```

### `shisa vouch`

```text
usage: shisa vouch verify [path]

commands:
  verify [path] validate VOUCHES format; defaults to ./VOUCHES
```
