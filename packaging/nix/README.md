# Nix packaging

This directory stages the Shisa derivation for a future nixpkgs PR.

Build locally with:

```sh
nix-build -E 'let pkgs = import <nixpkgs> {}; in pkgs.callPackage ./packaging/nix {}'
```

Notes:

- The derivation requires Zig 0.15.2 or newer.
- The in-repo source uses `lib.cleanSource ../..`; a nixpkgs PR should replace this with `fetchFromGitHub`.
- `doCheck` is disabled because `zig build test` currently includes shell integration tests that require non-minimal runtime tools such as `fish`, `nu`, `pwsh`, `expect`, and `tmux`.
