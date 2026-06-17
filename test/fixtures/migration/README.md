# Migration Fixtures

Representative importer inputs live here:

- `starship/representative.toml`: Starship TOML with a single-line `format`.
- `p10k/representative.p10k.zsh`: Powerlevel10k `.p10k.zsh` assignment excerpt.
- `oh-my-posh/representative.omp.json`: Oh My Posh theme JSON with palette, layout, and unsupported segment coverage.
- `tide/representative.fish`: Tide/Fish variable export excerpt.
- `pure/README.md`: Pure has no input file; `shisa import-pure` emits a fixed preset.

The fixtures are intentionally small so snapshot drift is attributable to importer behavior, not upstream churn.
