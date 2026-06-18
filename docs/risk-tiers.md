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

When multiple cloud contexts are present, Shisa classifies each provider value and uses the highest tier. For example, an AWS profile classified as `prod` and a Kubernetes context classified as `dev` produce an overall `prod` tier.

Prompt background-bar palette slots are configured in `shisa.toml`:

```toml
[modules.risk_tier]
unknown_bg = "muted"
dev_bg = "success"
staging_bg = "warning"
prod_bg = "danger"
```

When `risk_tier` is included in the prompt module list, the rendered segment also carries an ASCII glyph: `D` for dev, `S` for staging, and `!` for prod. The glyph and tier text remain visible when color is disabled.

Explain a value:

```sh
shisa cloud explain api-prd-use1
```
