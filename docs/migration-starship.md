# Starship Migration Warnings

`shisa import-starship` maps prompt modules that have Shisa equivalents. Unmapped Starship modules should be preserved as custom modules or capability-gated plugins.

Useful flags:

```sh
shisa import-starship ~/.config/starship.toml --dry-run
shisa import-starship ~/.config/starship.toml --diff
shisa import-starship ~/.config/starship.toml --output ~/.config/shisa/shisa.toml
```

Full map: `docs/starship-module-map.md`.
