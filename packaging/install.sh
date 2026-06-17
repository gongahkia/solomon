#!/bin/sh
set -eu

repo="${SHISA_GITHUB_REPO:-gongahkia/shisa}"
version="${SHISA_VERSION:-latest}"
install_dir="${SHISA_INSTALL_DIR:-$HOME/.local/bin}"

usage() {
  cat <<'EOF'
usage: install.sh [--repo OWNER/REPO] [--version TAG|latest] [--dir DIR]

Environment:
  SHISA_GITHUB_REPO  GitHub repository. Default: gongahkia/shisa.
  SHISA_VERSION      Release tag or latest. Default: latest.
  SHISA_INSTALL_DIR  Install directory. Default: ~/.local/bin.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'install.sh: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      [ "$#" -ge 2 ] || { printf 'install.sh: --repo needs a value\n' >&2; exit 1; }
      repo="$2"
      shift 2
      ;;
    --version)
      [ "$#" -ge 2 ] || { printf 'install.sh: --version needs a value\n' >&2; exit 1; }
      version="$2"
      shift 2
      ;;
    --dir)
      [ "$#" -ge 2 ] || { printf 'install.sh: --dir needs a value\n' >&2; exit 1; }
      install_dir="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'install.sh: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need curl
need tar
need shasum
need install
need mktemp

case "$(uname -s)" in
  Darwin) os=macos ;;
  Linux) os=linux ;;
  *) printf 'install.sh: unsupported OS: %s\n' "$(uname -s)" >&2; exit 1 ;;
esac

case "$(uname -m)" in
  arm64|aarch64) arch=arm64 ;;
  x86_64|amd64) arch=x64 ;;
  *) printf 'install.sh: unsupported arch: %s\n' "$(uname -m)" >&2; exit 1 ;;
esac

if [ "$version" = "latest" ]; then
  tag="$(
    curl -fsSL "https://api.github.com/repos/$repo/releases/latest" |
      sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' |
      head -n 1
  )"
  [ -n "$tag" ] || { printf 'install.sh: could not resolve latest release\n' >&2; exit 1; }
else
  tag="$version"
fi

name="shisa-$tag-$os-$arch"
archive="$name.tar.gz"
base_url="https://github.com/$repo/releases/download/$tag"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT INT HUP TERM

curl -fsSL "$base_url/$archive" -o "$work/$archive"
curl -fsSL "$base_url/$archive.sha256" -o "$work/$archive.sha256"

expected="$(awk '{ print $1; exit }' "$work/$archive.sha256")"
actual="$(shasum -a 256 "$work/$archive" | awk '{ print $1; exit }')"
[ "$expected" = "$actual" ] || {
  printf 'install.sh: checksum mismatch for %s\n' "$archive" >&2
  exit 1
}

tar -xzf "$work/$archive" -C "$work"
mkdir -p "$install_dir"
install -m 0755 "$work/$name/shisa" "$install_dir/shisa"
install -m 0755 "$work/$name/shisad" "$install_dir/shisad"

printf 'installed shisa %s to %s\n' "$tag" "$install_dir"
