BIN ?= close-enough
BUILD_FLAGS := -trimpath -buildvcs=false -mod=readonly

.PHONY: build test vet

build:
	go build $(BUILD_FLAGS) -o $(BIN) ./cmd/close-enough

test:
	go test -race ./...

vet:
	go vet ./...
