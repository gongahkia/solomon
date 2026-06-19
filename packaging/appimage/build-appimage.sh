#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
version="${SHISA_VERSION:-$(git -C "$repo_root" describe --tags --always --dirty 2>/dev/null || printf 'dev')}"
prefix="${SHISA_APPIMAGE_PREFIX:-$repo_root/zig-out/appimage/prefix}"
appdir="${SHISA_APPDIR:-$repo_root/zig-out/appimage/Shisa.AppDir}"
out_dir="${SHISA_APPIMAGE_OUT_DIR:-$repo_root/zig-out/appimage}"
appimagetool="${APPIMAGETOOL:-appimagetool}"
appimage_arch="${SHISA_APPIMAGE_ARCH:-x86_64}"
build_release=1
appdir_only=0

usage() {
  cat <<'EOF'
usage: packaging/appimage/build-appimage.sh [options]

Options:
  --appdir-only       Build AppDir but do not run appimagetool.
  --no-build          Use an existing SHISA_APPIMAGE_PREFIX instead of running zig build release.
  --prefix DIR        Staged release prefix. Default: zig-out/appimage/prefix.
  --appdir DIR        AppDir output path. Default: zig-out/appimage/Shisa.AppDir.
  --output-dir DIR    AppImage output directory. Default: zig-out/appimage.
  --version VERSION   AppImage version string. Default: git describe.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'build-appimage: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --appdir-only)
      appdir_only=1
      shift
      ;;
    --no-build)
      build_release=0
      shift
      ;;
    --prefix)
      [ "$#" -ge 2 ] || { printf 'build-appimage: --prefix needs a value\n' >&2; exit 1; }
      prefix="$2"
      shift 2
      ;;
    --appdir)
      [ "$#" -ge 2 ] || { printf 'build-appimage: --appdir needs a value\n' >&2; exit 1; }
      appdir="$2"
      shift 2
      ;;
    --output-dir)
      [ "$#" -ge 2 ] || { printf 'build-appimage: --output-dir needs a value\n' >&2; exit 1; }
      out_dir="$2"
      shift 2
      ;;
    --version)
      [ "$#" -ge 2 ] || { printf 'build-appimage: --version needs a value\n' >&2; exit 1; }
      version="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'build-appimage: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need install
need mkdir

if [ "$(uname -s)" != "Linux" ]; then
  printf 'build-appimage: AppImage packaging must run on Linux\n' >&2
  exit 1
fi

if [ "$build_release" -eq 1 ]; then
  need zig
  zig build release --prefix "$prefix"
fi

for bin in shisa shisad; do
  [ -x "$prefix/bin/$bin" ] || {
    printf 'build-appimage: missing executable: %s/bin/%s\n' "$prefix" "$bin" >&2
    exit 1
  }
done

rm -rf "$appdir"
mkdir -p "$appdir/usr/bin" \
  "$appdir/usr/share/applications" \
  "$appdir/usr/share/icons/hicolor/scalable/apps" \
  "$appdir/usr/share/licenses/shisa" \
  "$appdir/usr/share/doc/shisa" \
  "$out_dir"

install -m 0755 "$prefix/bin/shisa" "$appdir/usr/bin/shisa"
install -m 0755 "$prefix/bin/shisad" "$appdir/usr/bin/shisad"
install -m 0644 "$repo_root/LICENSE" "$appdir/usr/share/licenses/shisa/LICENSE"
install -m 0644 "$repo_root/README.md" "$appdir/usr/share/doc/shisa/README.md"

cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
set -eu
root="$(dirname "$(readlink -f "$0")")"
exec "$root/usr/bin/shisa" "$@"
APPRUN
chmod 0755 "$appdir/AppRun"

cat > "$appdir/usr/share/applications/shisa.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Shisa
Comment=Daemon-backed async-first cross-shell prompt
Exec=shisa
Icon=shisa
Terminal=true
Categories=Utility;ConsoleOnly;
DESKTOP

cat > "$appdir/usr/share/icons/hicolor/scalable/apps/shisa.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#101820"/>
  <path d="M26 35h76v14H26zM26 57h50v14H26zM26 79h66v14H26z" fill="#f2f7f2"/>
</svg>
SVG

ln -s usr/share/applications/shisa.desktop "$appdir/shisa.desktop"
ln -s usr/share/icons/hicolor/scalable/apps/shisa.svg "$appdir/shisa.svg"
ln -s shisa.svg "$appdir/.DirIcon"

if [ "$appdir_only" -eq 1 ]; then
  printf 'built AppDir at %s\n' "$appdir"
  exit 0
fi

need "$appimagetool"
ARCH="$appimage_arch" "$appimagetool" "$appdir" "$out_dir/Shisa-$version-$appimage_arch.AppImage"
