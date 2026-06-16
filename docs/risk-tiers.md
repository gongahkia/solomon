# Risk Tiers

`risk_tier` classifies context names into `prod`, `staging`, `dev`, or `unknown`.

Default rules:

- `prod`, `production`, `live`, and `*-prd-*` classify as `prod`.
- `stg` and `staging` classify as `staging`.
- `dev` and `sandbox` classify as `dev`.

User rules live at `~/.config/shisa/risk_tiers.toml`:

```toml
prod = ["critical", "*-payments-*"]
staging = ["preprod"]
dev = ["local"]
```

String rules match case-insensitive path/name tokens. Rules containing `*` match the full value as a case-insensitive glob. Higher-risk matches win.
