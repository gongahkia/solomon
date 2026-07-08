# E2E Docker Matrix

Run:

```sh
test/e2e/docker-shells.sh
test/e2e/docker-shells.sh --matrix test/e2e/hardening.tsv
```

The default matrix lives in `test/e2e/docker-matrix.tsv`. Each row builds a distro image, runs `zig build --seed 0 debug` inside the container, starts `shisad`, and asserts bash, zsh, and fish prompt output includes dirty Git state.

Set `SHISA_DOCKER_E2E_FILTER=ubuntu-24.04` or `--filter ubuntu-24.04` to run one row. Set `SHISA_DOCKER_E2E_ZIG_VERSION=0.15.2` to override Zig. Default `docker-matrix.tsv` runs standard rows only; pass `--include-hardening` or use `--matrix test/e2e/hardening.tsv` for the heavy rows. `--require-hardening` converts missing hardening prerequisites from skips to failures.

Current rows:

- `ubuntu-24.04`: `bash,zsh,fish`
- `fedora-40`: `bash,zsh,fish`
- `arch-rolling`: `bash,zsh,fish`, `linux/amd64` on Apple Silicon because the official Arch image has no arm64 manifest here

Arch notes: pacman's fetch sandbox is disabled for Docker seccomp/qemu compatibility, and `.sframe` is stripped from startup objects because Zig 0.15.2 cannot link Arch rolling's GCC 16 startup objects as-is.

## Hardening Rows

The heavy matrix lives in `test/e2e/hardening.tsv` and is gated in CI to run on `push` to `main`, or on pull requests labeled `area/ci`.

Rows:

- `systemd-nspawn-fedora`: Fedora image with `systemd-container`; asserts `systemd-nspawn --version`, shisad boot, socket under tmpfs runtime dir, prompt render, and doctor exit 0.
- `rootless-podman-fedora`: Fedora image with Podman; asserts rootless Podman is usable, then the same shisad/socket/prompt/doctor checks.
- `rootless-podman-rhel`: UBI 9 image with Podman; same assertions with bash/zsh coverage.
- `distrobox-fedora`: Fedora image with Distrobox; asserts Distrobox availability and sets Distrobox-style container metadata before the common checks.
- `distrobox-arch`: Arch image with Distrobox; same assertions on `linux/amd64`.
- `wayland-sway-fedora`: Fedora image with Sway; starts `WLR_BACKENDS=headless` and confirms a Wayland-only session before the common checks.

Prerequisites:

- Docker must support privileged containers and `--tmpfs /tmp:exec,mode=1777`.
- Podman and Distrobox rows require nested container support inside the built image.
- The Wayland row requires Sway headless startup with the pixman renderer.
