# Oh My Posh Migration Warnings

`shisa import-oh-my-posh` maps prompt segments that have Shisa equivalents. Unmapped Oh My Posh segments, templates, or colors should be preserved as custom modules, theme edits, or capability-gated plugins.

Useful flags:

```sh
shisa import-oh-my-posh theme.omp.json --dry-run
shisa import-oh-my-posh theme.omp.json --diff
shisa import-oh-my-posh theme.omp.json --output ~/.config/shisa/shisa.toml
```

Full map: `docs/oh-my-posh-segment-map.md`.
