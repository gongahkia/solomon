# Kubernetes deployment

The Helm chart is at `deploy/helm/shibahama`. It deploys one replica because the
service store uses one read-write-once persistent volume. The chart creates no
credentials: create a Secret containing `encryption-key` and `api-key` first.

```bash
kubectl create namespace shibahama
kubectl -n shibahama create secret generic shibahama-secrets \
  --from-literal=encryption-key="$(openssl rand -hex 32)" \
  --from-literal=api-key="$(openssl rand -hex 32)"
helm upgrade --install shibahama deploy/helm/shibahama \
  --namespace shibahama \
  --set secrets.existingSecret=shibahama-secrets
```

The default chart enables RBAC enforcement, persistence, read-only filesystem,
non-root execution, resource limits, and a port-restricted NetworkPolicy.
Ingress is disabled. Configure exact host/TLS settings through `ingress`; configure
OIDC through `oidc.issuer`, `oidc.audience`, and optionally `oidc.caConfigMap`.

Validate the chart with `scripts/ci/helm-lint.sh`; a Docker-backed kind smoke run
is available through `scripts/ci/helm-kind-smoke.sh`.
