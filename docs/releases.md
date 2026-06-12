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

## Rust Crates

The publishable Rust crates are:

- `shibahama-core`
- `shibahama-cli`

The Rust crates used only for Python and Node native bindings are marked
`publish = false` to avoid accidental crates.io uploads.

Build the core crate package and dry-run the core crate publish:

```sh
scripts/release/rust-publish.sh
```

Publish after crates.io auth is configured:

```sh
CARGO_REGISTRY_TOKEN=... SHIBAHAMA_PUBLISH=1 scripts/release/rust-publish.sh
cargo install shibahama-cli --version 0.1.0
```

`shibahama-cli` depends on `shibahama-core = 0.1.0`, so it cannot be fully
packaged or dry-run against crates.io until the core crate exists in the
crates.io index. Publish the core crate first, wait for the index, then publish
the CLI.

## v0.1.0 Release Sequence

Actual `v0.1.0` release remains blocked until crates.io, TestPyPI/PyPI, and npm
auth or trusted publishing are configured. The local preflight sequence is:

```sh
scripts/release/rust-publish.sh
scripts/release/python-publish.sh testpypi
scripts/release/npm-publish.sh
```

After all registry installs are verified, tag and push:

```sh
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```
