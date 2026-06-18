# Fuzz Nightly

The nightly fuzz workflow is `.github/workflows/fuzz.yml`. It runs bounded `zig build test --fuzz`; OSS-Fuzz integration lives under `fuzz/oss-fuzz/`.

| Target | Harness | Nightly evidence |
| --- | --- | --- |
| Frame deframer | `src/proto/frame.zig` test `fuzz decoder invariants`; OSS-Fuzz export `shisa_fuzz_frame_decode` | `.github/workflows/fuzz.yml` scheduled run plus OSS-Fuzz build files |
| JSON request decoder | `src/proto/types.zig` test `fuzz request decoder invariants` | `.github/workflows/fuzz.yml` scheduled `zig build test --fuzz` run |

When adding a target, include the source parser/decoder, seed corpus, expected recoverable errors, and crash retention path.
