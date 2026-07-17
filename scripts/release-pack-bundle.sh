#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  exit 2
fi

validator=$1
source=$2
archive=$3
root=$4
case "$root" in
  ""|*/*|*\\*|*..*) exit 2 ;;
esac
case "$archive" in
  *.tar.gz) ;;
  *) exit 2 ;;
esac
[ -x "$validator" ]
[ -d "$source" ]
set -- "$source"/*.json
[ -f "$1" ]
for pack in "$@"; do
  [ -f "$pack" ]
  [ ! -L "$pack" ]
  "$validator" pack validate "$pack"
done
for entry in "$source"/*; do
  [ -f "$entry" ]
  [ ! -L "$entry" ]
  case "$entry" in
    *.json) ;;
    *) exit 2 ;;
  esac
done
mkdir -p "$(dirname "$archive")"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM
mkdir "$temporary/$root"
for pack in "$@"; do
  cp "$pack" "$temporary/$root/$(basename "$pack")"
done
tar -C "$temporary" -czf "$archive" "$root"
