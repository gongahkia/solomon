# Tide Migration Warnings

`shisa import-tide` maps exported Tide items that have Shisa equivalents. Unmapped Tide items and Fish-specific layout settings should be preserved as custom modules, theme edits, or capability-gated plugins.

Useful flags:

```sh
shisa import-tide tide-settings.fish --dry-run
shisa import-tide tide-settings.fish --diff
shisa import-tide tide-settings.fish --output ~/.config/shisa/shisa.toml
```

Full map: `docs/tide-item-map.md`.
