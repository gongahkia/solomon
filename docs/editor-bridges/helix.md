# Helix Bridge

Helix statusline config is TOML under `[editor.statusline]`.

```toml
[editor.statusline]
left = ["mode", "spinner", "version-control"]
center = ["file-name"]
right = ["diagnostics", "workspace-diagnostics", "selections", "position", "file-encoding", "file-line-ending", "file-type"]
separator = "|"
```

Merge `contrib/editor-bridges/helix-shisa.toml` into `~/.config/helix/config.toml`.

Bridge mapping:

| Shisa topic | Helix element |
| --- | --- |
| `vcs.summary` | `version-control` |
| `diagnostics.summary` | `diagnostics`, `workspace-diagnostics` |
| `editor.position` | `position`, `selections` |
| `buffer.identity` | `file-name`, `file-type` |

Helix does not expose a native external statusline command hook. The checked-in TOML is a Shisa-compatible layout using supported Helix statusline elements; native topic streaming remains in the bridge layer, not in Helix config.
