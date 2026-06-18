# CLI Reference

Generated from `shisa --help` with `zig build cli-docs`.

## `shisa`

```text
usage: shisa <command> [options]

commands:
  ai            local AI helpers: status, redact, bench, risk, explain, nextcmd, nl2cmd
  bench         benchmark prompt render via hyperfine
  cache         dump or clear cache state
  cloud         cloud helpers: audit, doctor, explain, preexec
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
  init          write default shisa.toml; --a11y uses the a11y theme
  pin           mark a path as never-evicted
  plugin        new, lint, pack, install, list, enable, disable, or trust plugins
  prompt        render prompt through shisad; --a11y strips ANSI and normalizes glyphs
  render        alias for prompt; --explain-a11y dumps segment labels
  report        write a redacted support bundle .tar.gz
  stack         dump detected stacked-diff metadata
  supervisor    run shisad under a crash-restart supervisor
  theme         validate theme files
  vouch         verify VOUCHES governance file
  worktrees     list Git worktrees and mark active

options:
  -h, --help    print help
      --version print version
```

## Command Help

### `shisa ai`

```text
usage: shisa ai <command> [args]

commands:
  status        show local model, cloud provider, and audit status
  redact        test or edit local redaction literal rules
  bench         benchmark local Ollama generation
  risk          classify command risk
  explain       explain a command
  nextcmd       suggest a next command from local context
  nl2cmd        convert ?? input to a command suggestion
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
  gallery [--no-open]
                    generate a local static gallery and open it
```

### `shisa vouch`

```text
usage: shisa vouch verify [path]

commands:
  verify [path] validate VOUCHES format; defaults to ./VOUCHES
```

