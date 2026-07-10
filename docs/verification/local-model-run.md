<!-- SPDX-License-Identifier: Apache-2.0 -->

# Local Model Verification Run

Date: 2026-07-10

Environment:

- Ollama 0.31.1 on `http://127.0.0.1:11434`
- model: `qwen2.5-coder:1.5b`
- command: `make demo-local`

Verified output:

```text
1 passed
```

Assertions covered:

- `/answer` used the full recall -> boundary -> router -> local model path.
- recalled context was non-empty.
- local model response text was non-empty.
- model-visible prompt did not contain raw `Client A`.
- model-visible prompt did contain `[CLIENT_1]`.
- model audit reported `endpoint=local` and `crossed_boundary=false`.
