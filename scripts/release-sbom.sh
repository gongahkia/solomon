#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
  exit 2
fi

generator=$1
module=$2
output=$3
goos=$4
goarch=$5
case "$goos-$goarch" in
  linux-amd64|linux-arm64|darwin-amd64|darwin-arm64|windows-amd64) ;;
  *) exit 2 ;;
esac
case "$output" in
  *.cdx.json) ;;
  *) exit 2 ;;
esac
[ -x "$generator" ]
[ -f "$module/go.mod" ]

GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 "$generator" app -json -output "$output" -main cmd/solomon "$module"
test -s "$output"
