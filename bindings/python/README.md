# Python Bindings

Python package and PyO3 bindings for Shibahama.

## Development

Build and install the extension into an active virtual environment:

```sh
python -m pip install maturin
python -m maturin develop
```

Then verify the package imports:

```py
import shibahama

assert shibahama.version() == shibahama.__version__
```

The Python wrapper exposes the practical core operations: write, recall,
timeline, reinforce, `why`, event/audit drill-down, consolidation, challenge,
affirm, correct, pin, and unpin. Complex drill-down reports are returned as
plain dictionaries.

`LangChainMemory.clear()` and `LangChainMemory.aclear()` are
compatibility-only no-ops. They do not delete or invalidate durable Shibahama
memories; use separate stores or namespaces when a caller needs isolated
context.
