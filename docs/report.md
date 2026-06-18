# Support Report

`shisa report` writes a local support bundle:

```sh
shisa report --output shisa-report.tar.gz
```

Default output is `./shisa-report-<timestamp>.tar.gz`.

The archive contains:

- `README.txt`: bundle manifest and redaction note
- `config.redacted.toml`: active config, or built-in defaults when no config file exists
- `shisad.log.redacted`: last 1MiB of the daemon log, or missing/unreadable status
- `bench.txt`: local prompt payload microbench metadata

Config and logs are redacted before archive creation. The built-in rules replace documented credential patterns with `[redacted]`, including password/token/secret/API-key fields, AWS credentials, kubeconfig key data, SSH `IdentityFile`, bearer tokens, GitHub `gh*_` tokens, `sk-` provider keys, PEM private-key blocks, and 12-digit cloud account ids.
