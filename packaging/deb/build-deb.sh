#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
out_dir="${1:-$repo_root/dist}"
version="${SHISA_VERSION:-}"
arch="${SHISA_DEB_ARCH:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'build-deb: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

if [ -z "$version" ]; then
  version="$(awk -F '"' '/\.version =/ { print $2; exit }' "$repo_root/build.zig.zon")"
fi

if [ -z "$arch" ]; then
  if command -v dpkg >/dev/null 2>&1; then
    arch="$(dpkg --print-architecture)"
  else
    case "$(uname -m)" in
      x86_64) arch=amd64 ;;
      aarch64|arm64) arch=arm64 ;;
      *) printf 'build-deb: set SHISA_DEB_ARCH for this host\n' >&2; exit 1 ;;
    esac
  fi
fi

need zig
need dpkg-deb

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

install_prefix="$work/install"
pkgroot="$work/pkg"
pkg="shisa_${version}_${arch}"

mkdir -p "$out_dir" "$pkgroot/DEBIAN"

cd "$repo_root"
zig build release --prefix "$install_prefix"

install -Dm755 "$install_prefix/bin/shisa" "$pkgroot/usr/bin/shisa"
install -Dm755 "$install_prefix/bin/shisad" "$pkgroot/usr/bin/shisad"
install -Dm644 "$repo_root/README.md" "$pkgroot/usr/share/doc/shisa/README.md"
install -Dm644 "$repo_root/LICENSE" "$pkgroot/usr/share/doc/shisa/copyright"
install -Dm644 "$repo_root/init/shisa.zsh" "$pkgroot/usr/share/shisa/init/shisa.zsh"
install -Dm644 "$repo_root/init/shisa.bash" "$pkgroot/usr/share/shisa/init/shisa.bash"
install -Dm644 "$repo_root/init/shisa.fish" "$pkgroot/usr/share/shisa/init/shisa.fish"
install -Dm644 "$repo_root/init/shisa.nu" "$pkgroot/usr/share/shisa/init/shisa.nu"
install -Dm644 "$repo_root/init/shisa.ps1" "$pkgroot/usr/share/shisa/init/shisa.ps1"
install -d "$pkgroot/usr/share/shisa"
cp -R "$repo_root/themes" "$pkgroot/usr/share/shisa/themes"
cp -R "$repo_root/examples" "$pkgroot/usr/share/shisa/examples"

cat > "$pkgroot/DEBIAN/control" <<EOF
Package: shisa
Version: $version
Section: shells
Priority: optional
Architecture: $arch
Depends: libc6
Maintainer: Shisa maintainers <angryapplegravy@gmail.com>
Description: daemon-backed async-first cross-shell prompt
 Shisa keeps slow prompt work out of the shell by rendering through
 a per-user daemon with cached prompt modules.
EOF

dpkg-deb --root-owner-group --build "$pkgroot" "$out_dir/$pkg.deb"
sha256sum "$out_dir/$pkg.deb" > "$out_dir/$pkg.deb.sha256"
printf '%s\n' "$out_dir/$pkg.deb"
