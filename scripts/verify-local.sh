#!/bin/sh
set -eu

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT HUP INT TERM

make ci
make latency-gate
GOOS=windows GOARCH=amd64 go vet ./...
GOOS=windows GOARCH=amd64 go test -c -o "$temporary/solomon-windows.test.exe" ./cmd/solomon
GOOS=windows GOARCH=amd64 go test -c -o "$temporary/daemon-windows.test.exe" ./internal/daemon
