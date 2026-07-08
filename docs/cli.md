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
  import-starship <path>
                translate starship.toml to shisa.toml
  import-p10k <path>
                translate .p10k.zsh to shisa.toml
  import-oh-my-posh <path>
                translate Oh My Posh JSON/YAML to shisa.toml
  import-tide <path>
                translate Tide fish settings to shisa.toml
  import-pure
                print the minimal Pure-compatible preset
  init          write default shisa.toml; --a11y and shell notification prefs supported
  pin           mark a path as never-evicted
  plugin        new, lint, doctor, verify, search, pack, install, list, enable, disable, or trust plugins
  prompt        render prompt through shisad; --right prints configured right prompt
  render        alias for prompt; --explain-a11y dumps segment labels
  report        write a redacted support bundle .tar.gz
  supervisor    run shisad under a crash-restart supervisor
  theme         validate theme files
  trace         render once with module timing trace on stderr
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

### `shisa font`

```text
usage: shisa font check

commands:
  check         render Nerd Font, Unicode, and ASCII glyph probes
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

### `shisa vouch`

```text
usage: shisa vouch verify [path]

commands:
  verify [path] validate VOUCHES format; defaults to ./VOUCHES
```
