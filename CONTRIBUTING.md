# Contributing

Shibahama is not accepting broad feature contributions until the core architecture settles, but
bug reports, focused fixes, documentation improvements, and benchmark feedback are welcome.

## Local Checks

Before opening a pull request, run:

```sh
scripts/ci/rust.sh
scripts/ci/python-binding-smoke.sh
scripts/ci/node-binding-smoke.sh
```

Optional pre-commit hooks are provided through `pre-commit`:

```sh
pre-commit install
pre-commit run --all-files
```

## Commit Scope

Keep changes focused. Architecture, storage format, public API, and benchmark changes should
include tests or documentation that explain the behavioral contract they introduce.

## Security

Do not commit secrets, credentials, benchmark API keys, private datasets, or user memory dumps.
Treat stored memories as untrusted input and avoid examples that encourage executing retrieved
instructions blindly.
