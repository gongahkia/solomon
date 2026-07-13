<!-- SPDX-License-Identifier: Apache-2.0 -->

# Solomon Helm chart

This chart deploys the server SKU with an OIDC-configured API, optional console, one filesystem-source worker, a
post-install/post-upgrade migration Job, persistent ancillary state, Prometheus discovery, optional ServiceMonitor,
optional OTLP/HTTP tracing, and optional self-hosted PostgreSQL with pgvector.

The chart never creates secret values. Create these existing Secrets in the release namespace first:

| Value | Secret key | Purpose |
| --- | --- | --- |
| `database.existingSecret` | `database.passwordKey` | PostgreSQL password |
| `secrets.contentEncryption.existingSecret` | `secrets.contentEncryption.key` | Base64-encoded 32-byte content-encryption key |
| `auth.legacyApiKeySecret.name` | `auth.legacyApiKeySecret.key` | Only for `auth.mode=legacy-api-key` |

Use `helm upgrade --install --wait`; the migration hook runs after database resources become ready.

OIDC is the default and requires an HTTPS issuer, audience, and non-empty role mapping. Configure those values in a
private values file. The internal pgvector StatefulSet is enabled by default. Set `postgresql.enabled=false` and set
`database.host` to use a self-hosted external PostgreSQL deployment; `database.sslMode` is passed to psycopg as an
encoded DSN parameter.

The API, console, worker, and migration Job share the state PVC because source metadata, workflow metadata, tenant
registry, and the audit journal remain durable local files. Its default access mode is `ReadWriteMany`; select a
storage class that supports it. Keep the default single replica for each Solomon service until these ancillary stores
are externalized or coordinated with a distributed lease.

```bash
kubectl -n legal create secret generic solomon-database --from-literal=password='replace-me'
kubectl -n legal create secret generic solomon-content-encryption --from-literal=content_encryption_key="$(openssl rand -base64 32)"

helm upgrade --install solomon charts/solomon \
  --namespace legal --create-namespace --wait \
  --values values-production.yaml
```

Minimal OIDC values:

```yaml
image:
  repository: registry.example.com/solomon
  tag: 0.1.0
auth:
  mode: oidc
  oidc:
    issuer: https://idp.example.com
    audience: solomon-api
    roleMappings:
      firm-admin: admin
      firm-lawyer: lawyer
secrets:
  contentEncryption:
    existingSecret: solomon-content-encryption
    keyRef: kms://firm-keyring/solomon-content/v1
database:
  existingSecret: solomon-database
api:
  ingress:
    enabled: true
    className: nginx
    hosts:
      - host: api.solomon.example.com
        paths:
          - path: /
            pathType: Prefix
```

`observability.prometheus.enabled=true` adds standard scrape annotations to the API Service. Enable
`observability.prometheus.serviceMonitor.enabled` only when the Prometheus Operator CRD is installed. OTLP/HTTP export
is opt-in through `observability.openTelemetry`; point it at a self-hosted OpenTelemetry Collector.

Validate the chart without a Kubernetes cluster:

```bash
scripts/check_helm_chart.sh
```
