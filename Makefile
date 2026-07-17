BIN ?= close-enough
BUILD_FLAGS := -trimpath -buildvcs=false -mod=readonly
VERSION ?= dev
COMMIT ?= unknown
LDFLAGS := -X main.version=$(VERSION) -X main.commit=$(COMMIT)

.PHONY: build test vet

build:
	go build $(BUILD_FLAGS) -ldflags "$(LDFLAGS)" -o $(BIN) ./cmd/close-enough

test:
	go test -race ./...

vet:
	go vet ./...
