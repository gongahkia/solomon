.PHONY: build test vet

build:
	go build ./cmd/close-enough

test:
	go test -race ./...

vet:
	go vet ./...
