# Reproducibility

This page defines the controlled release-build invocation for Shisa. It is the baseline for later bit-identical artifact checks.

## Inputs

Use the toolchain pinned in:

- `.zigversion`
- `build.zig.zon`
- `.github/workflows/*.yml`

The Zig dependency set is explicit in `build.zig.zon`. It is empty for the current repo state.

## Baseline Invocation

Run from the repo root at the commit being released:

```sh
rm -rf zig-out .zig-cache .zig-cache-global
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" \
LC_ALL=C \
TZ=UTC \
zig build release \
  -Dtarget=aarch64-macos \
  -Dcpu=baseline \
  --cache-dir .zig-cache \
  --global-cache-dir .zig-cache-global \
  --seed 0 \
  --build-id=none \
  --prefix zig-out \
  --summary all
```

For another release target, change only `-Dtarget`. Keep `-Dcpu=baseline`, cache paths, seed, build ID mode, and environment variables fixed.

## Output

The release artifacts are:

- `zig-out/bin/shisa`
- `zig-out/bin/shisad`

Record artifact hashes with:

```sh
shasum -a 256 zig-out/bin/shisa zig-out/bin/shisad
```

## Current Limits

This invocation controls the project-level inputs. It is not yet proof that artifacts are bit-identical across hosts.

Known gaps:

- macOS Mach-O outputs include `LC_UUID` and code-signature data.
- Linux cross-builds need a separate release-target fix before they can join the reproducibility matrix.
- Cross-host artifact comparison is tracked as the next release-engineering TODO.

Until that comparison is complete, release notes should say "controlled build invocation", not "reproducible build".
