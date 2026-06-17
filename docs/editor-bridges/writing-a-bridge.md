# Writing A Shisa Bridge In 50 Lines

Editor bridges use the daemon socket and protocol v1 `subscribe` op.

The startup handshake is one length-prefixed JSON frame:

```text
u32_be payload_len
payload_len bytes of UTF-8 JSON
```

After the subscribe frame, the connection switches to NDJSON. The daemon first sends a `snapshot` event, then `delta`, `heartbeat`, or `error` events. Subscribe connections are read-only; mutating ops return `E_READONLY`.

```python
#!/usr/bin/env python3
import json, os, socket, struct, sys

TOPICS = ["cloud_ctx", "vcs.summary", "risk_tier"]

def default_socket():
    if sys.platform == "darwin":
        return os.path.join(os.environ["HOME"], "Library/Caches/shisa/shisa.sock")
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return os.path.join(runtime, "shisa.sock")
    return f"/run/user/{os.getuid()}/shisa.sock"

def frame(obj):
    payload = json.dumps(obj, separators=(",", ":")).encode()
    return struct.pack(">I", len(payload)) + payload

def render(event):
    topic = event.get("topic", "")
    data = event.get("data") or {}
    if event.get("kind") == "error":
        err = data.get("error") or {}
        return f"{topic}: {err.get('code', 'error')}"
    text = data.get("text") or data.get("value") or data.get("sequence")
    return f"{topic}: {text}" if text is not None else f"{topic}: {event.get('kind')}"

def main():
    path = os.environ.get("SHISA_SOCKET", default_socket())
    request = {
        "v": 1,
        "op": "subscribe",
        "request_id": "bridge-50",
        "topics": TOPICS,
        "backpressure_limit": 16,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(path)
        client.sendall(frame(request))
        stream = client.makefile("r", encoding="utf-8")
        for line in stream:
            if not line.strip():
                continue
            print(render(json.loads(line)), flush=True)

if __name__ == "__main__":
    main()
```

Set `SHISA_SOCKET` to override the default path. Keep bridge commands on subscribe connections to read-only ops: `ping`, `subscribe`, `unsubscribe`, `health`, `metrics`, and `version`.

References:

- `rfcs/0005-wire-protocol-v1.md`
- `docs/socket-paths.md`
- `docs/protocol/errors.md`
