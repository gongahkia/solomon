#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  exit 2
fi

archive=$1
goos=$2
goarch=$3
version=$4
case "$goos-$goarch" in
  linux-amd64|linux-arm64|darwin-amd64|darwin-arm64|windows-amd64) ;;
  *) exit 2 ;;
esac
case "$version" in
  v[0-9]* ) ;;
  *) exit 2 ;;
esac
[ -f "$archive" ]
root=$(basename "$archive")
case "$archive" in
  *.tar.gz)
    [ "$goos" != windows ]
    root=${root%.tar.gz}
    binary="$root/solomon"
    listing=$(tar -tzf "$archive")
    ;;
  *.zip)
    [ "$goos" = windows ]
    root=${root%.zip}
    binary="$root/solomon.exe"
    listing=$(unzip -Z1 "$archive")
    ;;
  *) exit 2 ;;
esac
[ "$root" = "solomon_${version}_${goos}_${goarch}" ]
expected_listing=$(printf '%s/\n%s\n' "$root" "$binary")
[ "$listing" = "$expected_listing" ]

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
case "$archive" in
  *.tar.gz) tar -xzf "$archive" -C "$temporary" ;;
  *.zip) unzip -q "$archive" -d "$temporary" ;;
esac
[ -f "$temporary/$binary" ]
[ ! -L "$temporary/$binary" ]
binary_path="$temporary/$binary"
output=$("$binary_path" version)
prefix="solomon $version ("
commit=${output#"$prefix"}
[ "$commit" != "$output" ]
case "$commit" in
  *')') ;;
  *) exit 1 ;;
esac
commit=${commit%)}
[ "${#commit}" -eq 40 ]
case "$commit" in
  *[!0-9a-f]*|'') exit 1 ;;
esac
runtime="$temporary/runtime"
mkdir -p "$runtime"
export XDG_RUNTIME_DIR="$runtime"
handshake=$("$binary_path" daemon request --operation handshake --shell smoke --session release-smoke --format json)
case "$handshake" in
  *'"version":1'*'"action":"ready"'*) ;;
  *) exit 1 ;;
esac
"$binary_path" daemon stop >/dev/null
