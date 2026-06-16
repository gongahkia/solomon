# IAM Whoami

`iam_whoami` reads cached identity data only.

AWS STS cache files use the raw `GetCallerIdentity` JSON shape:

```json
{
  "UserId": "AIDAEXAMPLE",
  "Account": "123456789012",
  "Arn": "arn:aws:iam::123456789012:user/alice"
}
```

The cache path is `~/.cache/shisa/aws-sts-<profile>.json`; unsafe profile names fall back to `default`.
