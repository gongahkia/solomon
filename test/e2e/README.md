# E2E Docker Matrix

Run:

```sh
test/e2e/docker-shells.sh
```

The matrix lives in `test/e2e/docker-matrix.tsv`. Each row builds a distro image, runs `zig build --seed 0 debug` inside the container, starts `shisad`, and asserts bash, zsh, and fish prompt output includes dirty Git state.

Set `SHISA_DOCKER_E2E_FILTER=ubuntu-24.04` to run one distro. Set `SHISA_DOCKER_E2E_ZIG_VERSION=0.15.2` to override Zig.

Current rows:

- `ubuntu-24.04`: `bash,zsh,fish`
- `fedora-40`: `bash,zsh,fish`
- `arch-rolling`: `bash,zsh,fish`, `linux/amd64` on Apple Silicon because the official Arch image has no arm64 manifest here

Arch notes: pacman's fetch sandbox is disabled for Docker seccomp/qemu compatibility, and `.sframe` is stripped from startup objects because Zig 0.15.2 cannot link Arch rolling's GCC 16 startup objects as-is.
