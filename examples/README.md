# Examples

Runnable examples and demo agents using Shibahama.

## Binding Quickstarts

Rust core API:

```sh
cargo run --manifest-path examples/rust/quickstart/Cargo.toml
```

Python binding:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip maturin
(
  cd bindings/python
  python -m maturin develop
)
python examples/python/basic_memory.py
```

Node binding:

```sh
(
  cd bindings/node
  npm install
  npm run build
)
node examples/node/basic-memory.mjs
```

## Demos

- `coding-agent/`: long-horizon coding-agent memory demo with a Tideline recording.
