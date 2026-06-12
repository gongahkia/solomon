<!-- SPDX-License-Identifier: Apache-2.0 -->

# Release Artifact Verification

Generated locally on 2026-06-12 for `v0.1.0`.

Commands run:

```bash
uv build
uv sync --extra packaging
uv run pyinstaller packaging/solomon-local.spec --noconfirm --clean
./dist/solomon-local --version
docker compose -f docker-compose.server.yml config
```

Verified outputs:

- `dist/solomon-0.1.0.tar.gz`
- `dist/solomon-0.1.0-py3-none-any.whl`
- `dist/solomon-local`
- `./dist/solomon-local --version` prints `0.1.0`
- Docker Compose server configuration renders with `solomon-server` on port `8140`
