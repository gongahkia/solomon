# Uninstall

Remove shell integration only:

```sh
shisa uninstall --shell zsh
exec zsh
```

Restore Starship while removing the Shisa hook:

```sh
shisa uninstall --shell zsh --restore-starship
exec zsh
```

Remove hooks from all supported shell startup files:

```sh
shisa uninstall --all-shells
```

Stop the daemon before removing files:

```sh
pkill shisad
pkill shisa-supervisor
```

Preview full removal:

```sh
shisa uninstall --all-shells --purge --dry-run
```

Fully remove local Shisa-owned state:

```sh
shisa uninstall --all-shells --purge --yes
```

`--purge --yes` removes:

- `~/.config/shisa`
- `~/.cache/shisa`
- `~/.local/state/shisa`
- `~/Library/Caches/shisa`
- `~/Library/Logs/shisa`
- `~/Library/Application Support/shisa`
- the default daemon socket and lock file

If Shisa was built from source, remove the clone after uninstalling:

```sh
rm -rf /path/to/shisa
```

If Shisa binaries were copied elsewhere, remove those copied binaries from your `PATH`.
