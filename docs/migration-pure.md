# Pure Migration Warnings

`shisa import-pure` emits the fixed Pure-compatible Shisa preset. Pure has no portable source config, so there are normally no unmapped keys.

Useful flags:

```sh
shisa import-pure --dry-run
shisa import-pure --diff
shisa import-pure --output ~/.config/shisa/shisa.toml
```

Background: `docs/pure-import.md`.
