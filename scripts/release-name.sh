#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  exit 2
fi

version=$1
goos=$2
goarch=$3
extension=$4
case "$version" in
  v[0-9]* ) ;;
  *) exit 2 ;;
esac
case "$version" in
  *[!0-9A-Za-z.+-]* ) exit 2 ;;
esac
case "$goos-$goarch-$extension" in
  linux-amd64-tar.gz|linux-arm64-tar.gz|darwin-amd64-tar.gz|darwin-arm64-tar.gz|windows-amd64-zip ) ;;
  *) exit 2 ;;
esac
printf 'solomon_%s_%s_%s.%s\n' "$version" "$goos" "$goarch" "$extension"
