# Tideline

TypeScript/React visual debugger for Shibahama memory state and event streams.

## Run

Start the Shibahama server:

```bash
cargo run -p shibahama-cli -- serve --path shibahama.redb --dimensions 2 --api-key dev
```

Start the debugger:

```bash
npm install
npm run dev
```

Open the Vite URL, set API to `http://127.0.0.1:8765`, namespace to the server namespace, and key to the API key.

## API

Tideline consumes the read-only server routes:

- `GET /tideline/snapshot?as_of_unix=...` returns the current namespace memory state, event replay records, and graph projection.
- `GET /tideline/recording?as_of_unix=...` returns the same schema as a portable session recording.
- `GET /tideline/live?as_of_unix=...` returns an SSE stream of periodic snapshot events.

The UI also calls `GET /why/{memory_id}` for the selected memory's trace.
