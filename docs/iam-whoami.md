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

GCP auth list cache files use `gcloud auth list --format=json` output:

```json
[
  {"account": "active@example.com", "status": "ACTIVE"}
]
```

The cache path is `~/.cache/shisa/gcloud-auth-list.json`.

Azure account cache files use `az account show --output json` output:

```json
{
  "name": "prod-sub",
  "user": {"name": "alice@example.com", "type": "user"}
}
```

The cache path is `~/.cache/shisa/az-account-show.json`.

Kubernetes whoami reads the active context user from kubeconfig (`KUBECONFIG` first path, or `~/.kube/config`) without invoking `kubectl`.
