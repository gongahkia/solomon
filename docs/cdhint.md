# cd hint

`cdhint` project detection is pure local filesystem inspection. It walks from the current directory upward and stops at the first recognized marker.

Enable the prompt segment by adding `cdhint` to the configured pipeline:

```toml
[prompt]
modules = ["cwd", "cdhint", "git_branch"]
```

Rendered hints are compact: `cd:node`, `cd:rust`, `cd:python`, or `cd:go`.

Current marker rules:

| Marker | Project kind |
| --- | --- |
| `package.json` | `node` |
| `Cargo.toml` | `rust` |
| `pyproject.toml` | `python` |
| `requirements.txt` | `python` |
| `setup.py` | `python` |
| `go.mod` | `go` |

Global config:

```toml
[modules.cdhint]
enabled = true
```

Set `enabled = false` to suppress the segment. To disable hints for one tree, place `.shisa-no-cdhint` in the current directory or any directory between the current directory and the detected project root.

The detector does not call a model, spawn tools, or read package contents.
