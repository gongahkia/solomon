<!-- SPDX-License-Identifier: Apache-2.0 -->

# Packaging

- `solomon-local.spec` is the PyInstaller entry for the offline local SKU.
- Docker Compose files at the repository root are for the server SKU and use the in-process Solomon boundary by
  default. Set `SOLOMON_BOUNDARY_BASE_URL` only for an explicitly externalized boundary deployment.
- `Dockerfile` and `docker-compose.production.yml` build a self-hosted server profile with pgvector, migrations,
  API, console, and a filesystem-source worker. See the production Compose section in the root README for secret files
  and the startup command.
- `charts/solomon` is the self-hosted Kubernetes chart. It requires existing secret references, supports OIDC,
  pgvector or an external PostgreSQL deployment, ingress, worker, migration hooks, and Prometheus/OTLP configuration.

## v0.1.0 release artifacts

Build the pip-installable artifacts:

```bash
uv build
```

Build the local desktop binary:

```bash
uv sync --extra packaging
uv run pyinstaller packaging/solomon-local.spec --noconfirm --clean
```

Expected outputs:

- `dist/solomon-0.1.0.tar.gz`
- `dist/solomon-0.1.0-py3-none-any.whl`
- `dist/solomon-local`

Python package release setup and the TestPyPI/PyPI runbooks are in [`docs/release.md`](../docs/release.md).

CI builds the binary on macOS and Linux, then runs the stale-house-view flow headlessly and compares its semantic
output with the configured server-SKU CLI:

```bash
uv run python scripts/smoke_local_binary.py --binary dist/solomon-local
```
