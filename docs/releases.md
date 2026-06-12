# Release Policy

Shibahama uses Semantic Versioning.

- Increment `MAJOR` for incompatible public API, storage format, binding, or protocol changes
  after a stable release exists.
- Increment `MINOR` for backwards-compatible features.
- Increment `PATCH` for backwards-compatible bug fixes, documentation fixes, and maintenance.
- Before `1.0.0`, `MINOR` releases may still contain breaking changes, but the changelog must call
  them out explicitly.

Every release must update `CHANGELOG.md`, tag the repository as `vMAJOR.MINOR.PATCH`, and keep
Cargo, Python, and Node package versions aligned unless a package has not shipped yet.

## Python Package

The Python package is built with maturin and uploaded with Twine. TestPyPI and
PyPI require separate credentials, and this machine currently has no
TestPyPI/PyPI token or trusted publishing setup.

Build and check artifacts locally without uploading:

```sh
scripts/release/python-publish.sh testpypi
```

Upload to TestPyPI when credentials are configured:

```sh
TEST_PYPI_TOKEN=... SHIBAHAMA_PUBLISH=1 scripts/release/python-publish.sh testpypi
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  shibahama==0.1.0
```

Only after TestPyPI installation works, upload to PyPI:

```sh
PYPI_TOKEN=... SHIBAHAMA_PUBLISH=1 scripts/release/python-publish.sh pypi
python -m pip install shibahama==0.1.0
```

## Node Package

The Node package uses napi-rs. This machine is not logged into npm (`npm whoami`
returns `ENEEDAUTH`), so upload is blocked until npm auth or trusted publishing
is configured.

Build, test, and dry-pack locally without uploading:

```sh
scripts/release/npm-publish.sh
```

Publish after npm auth is configured:

```sh
NODE_AUTH_TOKEN=... SHIBAHAMA_PUBLISH=1 scripts/release/npm-publish.sh
npm install shibahama@0.1.0
```

For public packages published from a public GitHub repository, prefer npm
trusted publishing so npm can generate provenance automatically.
