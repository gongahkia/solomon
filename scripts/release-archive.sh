#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
  exit 2
fi

binary=$1
archive=$2
root=$3
case "$root" in
  ""|*/*|*\\*|*..*) exit 2 ;;
esac
case "$archive" in
  *.tar.gz) ;;
  *) exit 2 ;;
esac
if [ ! -f "$binary" ] || [ -L "$binary" ]; then
  exit 1
fi
mkdir -p "$(dirname "$archive")"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
mkdir "$temporary/$root"
cp "$binary" "$temporary/$root/close-enough"
tar -C "$temporary" -czf "$archive" "$root"
