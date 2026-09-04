#!/bin/sh
set -eu

if [ "$#" -ne 5 ]; then
  exit 2
fi

auditor=$1
module=$2
output=$3
goos=$4
goarch=$5
case "$goos-$goarch" in
  linux-amd64|linux-arm64|darwin-amd64|darwin-arm64|windows-amd64) ;;
  *) exit 2 ;;
esac
case "$output" in
  *.licenses.csv) ;;
  *) exit 2 ;;
esac
[ -x "$auditor" ]
[ -d "$module/cmd/solomon" ]

cd "$module"
GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 "$auditor" check ./cmd/solomon
GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 "$auditor" report ./cmd/solomon > "$output"
test -s "$output"
