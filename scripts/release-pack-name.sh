#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  exit 2
fi

version=$1
case "$version" in
  v[0-9]* ) ;;
  *) exit 2 ;;
esac
case "$version" in
  *[!0-9A-Za-z.+-]* ) exit 2 ;;
esac
printf 'close-enough-packs_%s.tar.gz\n' "$version"
