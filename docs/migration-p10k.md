# Powerlevel10k Migration Warnings

`shisa import-p10k` maps prompt elements that have Shisa equivalents. Unmapped Powerlevel10k elements should be preserved as custom modules or capability-gated plugins.

Useful flags:

```sh
shisa import-p10k ~/.p10k.zsh --dry-run
shisa import-p10k ~/.p10k.zsh --diff
shisa import-p10k ~/.p10k.zsh --output ~/.config/shisa/shisa.toml
```

Full map: `docs/powerlevel10k-module-map.md`.
