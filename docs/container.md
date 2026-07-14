# Hardened container image

Build the image and emit its build provenance plus SPDX SBOM:

```bash
scripts/ci/container-build.sh
```

The artifacts are written to `target/container/build-metadata.json` and
`target/container/sbom.spdx.json`. The image is built from digest-pinned Rust,
Debian, BusyBox, Dockerfile frontend, and Syft inputs; Rust dependencies are
locked by `Cargo.lock`.

The runtime has no accepted positional arguments. It rejects every
`SHIBAHAMA_*` variable not listed below, runs as UID/GID `65532`, defaults to
enforced RBAC, writes only to its data volume, and requires encryption plus an
authenticated control path.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `SHIBAHAMA_DIMENSIONS` | yes | — | Positive vector dimension. |
| `SHIBAHAMA_ENCRYPTION_KEY` | yes | — | 64-character hexadecimal envelope key. |
| `SHIBAHAMA_API_KEY` | API-key mode | — | Static service credential. |
| `SHIBAHAMA_OIDC_ISSUER` | OIDC mode | — | Exact OIDC issuer; requires audience. |
| `SHIBAHAMA_OIDC_AUDIENCE` | OIDC mode | — | OIDC audience/client identifier; requires issuer. |
| `SHIBAHAMA_OIDC_PRINCIPAL_CLAIM` | no | `sub` | OIDC claim used for the opaque principal. |
| `SHIBAHAMA_OIDC_CA_CERT_PATH` | no | — | Additional PEM root trusted only for OIDC discovery and JWKS. |
| `SHIBAHAMA_DATA_PATH` | no | `/var/lib/shibahama/shibahama.redb` | Absolute durable-store path. |
| `SHIBAHAMA_BIND` | no | `0.0.0.0:8765` | Service socket address. |
| `SHIBAHAMA_NAMESPACE` | no | `default` | Default repository namespace. |
| `SHIBAHAMA_ENCRYPTION_KEY_ID` | no | `service-local` | Envelope-key identifier. |
| `SHIBAHAMA_RBAC_ENFORCE` | no | `true` | `true` requires explicit scoped RBAC grants. |
| `SHIBAHAMA_RBAC_ERASURE_MIN_ROLE` | no | CLI default | Role required for semantic erasure. |
| `SHIBAHAMA_RBAC_PROMOTION_MIN_ROLE` | no | CLI default | Role required for repository-to-team promotion. |
| `SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET` | no | — | One-time administrator bootstrap secret. |
| `SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS` | no | CLI default | Positive bootstrap-window duration. |
| `SHIBAHAMA_ADMIN_RECOVERY_SECRET` | no | — | Administrator recovery secret. |
| `SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW` | no | CLI default | Positive sustained rate-limit allowance. |
| `SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS` | no | CLI default | Positive rate-limit window. |
| `SHIBAHAMA_RATE_LIMIT_BURST` | no | CLI default | Positive rate-limit burst allowance. |
| `SHIBAHAMA_CORS_ORIGINS` | no | CLI default | Comma-separated exact origins. |
| `SHIBAHAMA_CORS_METHODS` | no | CLI default | Comma-separated allowed methods. |
| `SHIBAHAMA_CORS_HEADERS` | no | CLI default | Comma-separated allowed request headers. |
| `SHIBAHAMA_CORS_ALLOW_CREDENTIALS` | no | `false` | Whether CORS credential responses are enabled. |

At least `SHIBAHAMA_API_KEY`, or both OIDC issuer and audience, is required.
Mount a writable volume at `/var/lib/shibahama` for durable data.

For a local team environment with a persistent Shibahama store, PostgreSQL-backed
Keycloak, dynamic administrator bootstrap secret, and OIDC flow, run:

```bash
scripts/dev/team-up.sh
```

The script creates untracked mode-`0600` credentials in `.shibahama/team-compose`.
The checked-in Compose realm contains only the public `shibahama` client and its
audience mapper; it contains no users or secrets. CI verifies the deployment by
creating a temporary user, bootstrapping the OIDC administrator, and making both
scoped HTTP and MCP requests.

```bash
docker run --rm -p 8765:8765 \
  -v shibahama-data:/var/lib/shibahama \
  -e SHIBAHAMA_DIMENSIONS=1536 \
  -e SHIBAHAMA_ENCRYPTION_KEY="$(openssl rand -hex 32)" \
  -e SHIBAHAMA_API_KEY="$(openssl rand -hex 32)" \
  shibahama:ci
```
