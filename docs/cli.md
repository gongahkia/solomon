# CLI Reference

Generated from `shisa --help` with `zig build cli-docs`.

## `shisa`

```text
usage: shisa <command> [options]

commands:
  ai            local AI helpers: bench
  bench         benchmark prompt render via hyperfine
  cache         dump cache stats
  cloud         cloud helpers: audit, doctor, explain, preexec
  doctor        diagnose socket, config, plugins, lua, fsnotify
  explain       print resolved module pipeline
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
  init          write default shisa.toml
  pin           mark a path as never-evicted
  plugin        install, list, enable, disable, or trust plugins
  prompt        render prompt through shisad; --a11y strips ANSI and normalizes glyphs
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

### `shisa theme`

```text
usage: shisa theme validate <path>
```

### `shisa vouch`

```text
usage: shisa vouch verify [path]

commands:
  verify [path] validate VOUCHES format; defaults to ./VOUCHES
```

