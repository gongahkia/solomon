<!-- SPDX-License-Identifier: Apache-2.0 -->

# Packaging

- `solomon-local.spec` is the PyInstaller entry for the offline local SKU.
- Docker Compose files at the repository root are for the server SKU and assume Kaypoh server is configured
  separately through `SOLOMON_KAYPOH_BASE_URL`.

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
