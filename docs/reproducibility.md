# Reproducibility

[![release reproducibility gate](https://github.com/gongahkia/shisa/actions/workflows/release.yml/badge.svg)](https://github.com/gongahkia/shisa/actions/workflows/release.yml)

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
- `zig-out/bin/shisa-supervisor`

Record artifact hashes with:

```sh
shasum -a 256 zig-out/bin/shisa zig-out/bin/shisad zig-out/bin/shisa-supervisor
```

## Tagged Release Gate

The Ubuntu job in the tag-driven release workflow runs:

```sh
bash .github/scripts/reproducibility-check.sh
```

The script builds `release` twice with fixed `SOURCE_DATE_EPOCH`, locale, timezone, cache paths, seed, optional target, and build-id mode. It compares SHA-256 hashes for `shisa`, `shisad`, and `shisa-supervisor`, then fails the tagged release job on any mismatch.

The release workflow also runs the same check in two independent Ubuntu job slots, uploads each hash file, and diffs those files before publishing the GitHub Release.

The badge above reports the tag-driven release workflow status. For now, that means the Linux same-runner and two-job hash comparison gates passed, not that every platform artifact is bit-identical.

## Current Limits

This invocation controls the project-level inputs and checks two repeated builds on the same runner. It is not yet proof that artifacts are bit-identical across hosts.

Known gaps:

- Native macOS Mach-O outputs still include nondeterministic `LC_UUID` and code-signature data, so the reproducibility gate is Linux-only for now.
- Linux cross-builds need a separate release-target fix before they can join the reproducibility matrix.
- Cross-provider artifact comparison remains future release-engineering work.

Until multi-provider comparison is complete, release notes should say "Linux reproducibility check", not "reproducible build".
