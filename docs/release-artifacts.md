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

## Public Release Evidence

Published on 2026-06-13:

- GitHub release: [Solomon v0.1.0](https://github.com/gongahkia/solomon/releases/tag/v0.1.0)
- Remote tag: `v0.1.0`
- Uploaded release assets:
  - `solomon-0.1.0.tar.gz` SHA-256 `252714491de690339f7ef4eafccad45b611b8230bc30cba3501404c87478427f`
  - `solomon-0.1.0-py3-none-any.whl` SHA-256 `a134d2529f1bc3db1d72eb7c5646106b57fe8385fbbb8d69df1e1a3542ed8ca6`
  - `solomon-local` SHA-256 `4918a88b3b561c713e64bb8ab1995c2dc04d3179ea97b09240d25c71771e55d7`
