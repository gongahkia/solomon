# Style Guide

Shisa docs use short, direct prose. The project style is enforced with Vale on changed PR lines in `README.md`, `docs/`, and `rfcs/`.

## Voice

- Lead with the user-visible behavior.
- State conditions instead of using intensifiers.
- Keep performance claims scoped to a command, platform, fixture, or benchmark.
- Mark roadmap language as a target until release evidence exists.
- Prefer concrete nouns over filler phrases.

## Terms

<!-- vale off -->

| Use | Instead of |
| --- | --- |
| `filesystem` | file system |
| `fsnotify` | fs notify |
| `hot path` | hotpath, hot-path |
| `Lua` | lua |
| `LuaJIT` | luajit |
| `macOS` | macos, mac os |
| `PowerShell` | powershell |
| `zsh` | z shell |
| `Zig` | zig |

<!-- vale on -->

## Inclusive Language

Use precise alternatives for casual judgement words.

<!-- vale off -->

| Avoid | Prefer |
| --- | --- |
| sane | valid, supported, expected |
| crazy | unexpected, high, unusual |
| insane | extreme, invalid, unsupported |
| dumb | limited, accidental, inefficient |
| stupid | invalid, risky, incorrect |

<!-- vale on -->

## Claims

Absolute claims need a measurement, a scope, or a versioned contract. Prefer this shape:

- "Warm prompt render p99 is under 2 ms on the benchmark fixture."
- "The fallback prompt target is under 5 ms."
- "The daemon denies undeclared plugin capabilities."

Avoid broad claims that outgrow the available evidence.

## Local Check

Install Vale, then run:

```sh
vale README.md docs rfcs
```

CI runs the same style pack against changed PR lines and fails on warnings.
