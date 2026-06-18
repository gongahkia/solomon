# cd hint

`cdhint` project detection is pure local filesystem inspection. It walks from the current directory upward and stops at the first recognized marker.

Current marker rules:

| Marker | Project kind |
| --- | --- |
| `package.json` | `node` |
| `Cargo.toml` | `rust` |
| `pyproject.toml` | `python` |
| `requirements.txt` | `python` |
| `setup.py` | `python` |
| `go.mod` | `go` |

The detector does not call a model, spawn tools, or read package contents.
