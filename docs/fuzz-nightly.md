# Fuzz Nightly

The nightly fuzz workflow is `.github/workflows/fuzz.yml`. It runs bounded `zig build test --fuzz`; OSS-Fuzz integration lives under `fuzz/oss-fuzz/`.

| Target | Harness | Nightly evidence |
| --- | --- | --- |
| Frame deframer | `src/proto/frame.zig` test `fuzz decoder invariants`; OSS-Fuzz export `shisa_fuzz_frame_decode` | `.github/workflows/fuzz.yml` scheduled run plus OSS-Fuzz build files |
| JSON request decoder | `src/proto/types.zig` test `fuzz request decoder invariants` | `.github/workflows/fuzz.yml` scheduled `zig build test --fuzz` run |
| Lua bridge surface | `src/plugin/context.zig` test `fuzz ctx bridge function inputs`; `src/plugin/lua.zig` test `fuzz lua manifest bridge invariants`; OSS-Fuzz export `shisa_fuzz_context_input` | `.github/workflows/fuzz.yml` scheduled run plus OSS-Fuzz build files |
| Redaction rules | `src/ai/redact.zig` test `fuzz redaction invariants` | `.github/workflows/fuzz.yml` scheduled `zig build test --fuzz` run |

## Crash Retention

On a non-timeout fuzz failure, `.github/workflows/fuzz.yml` writes `fuzz-crash-<run_id>-<attempt>.tar.gz` with the fuzz log, run metadata, and matching cache crash/repro files. The bundle is uploaded as a 7-day GitHub Actions artifact and, when configured, copied to a private S3 bucket.

Private bucket upload requires repository secrets `FUZZ_CRASH_BUCKET` and `FUZZ_CRASH_AWS_ROLE_ARN`; `FUZZ_CRASH_AWS_REGION` may be set as a repository variable and defaults to `us-east-1`. The bucket must block public access, and the assumed role should be write-only for the `nightly/<owner>/<repo>/` prefix.

When adding a target, include the source parser/decoder, seed corpus, expected recoverable errors, and crash retention path.
