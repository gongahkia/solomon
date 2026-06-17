# Shisa VS Code Sample

Community-quality sample extension for reading Shisa `subscribe` events into a VS Code status bar item.

Status:

- Not published.
- Unix socket only.
- Uses protocol v1 `subscribe`.
- Intended as sample code, not an official Shisa commitment.

## Local Run

```sh
npm install
npm run compile
```

Open this directory in VS Code and run the extension host.

Settings:

| Setting | Default |
| --- | --- |
| `shisa.socket` | platform default |
| `shisa.topics` | `["cloud_ctx", "vcs.summary", "risk_tier"]` |
| `shisa.backpressureLimit` | `16` |

Commands:

- `Shisa: Connect`
- `Shisa: Disconnect`
- `Shisa: Refresh`
