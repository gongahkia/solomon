BIN ?= close-enough
BUILD_FLAGS := -trimpath -buildvcs=false -mod=readonly
VERSION ?= dev
COMMIT ?= unknown
LDFLAGS := -X main.version=$(VERSION) -X main.commit=$(COMMIT)

.PHONY: build test vet ci benchmark-pre-execution benchmark-path-cache benchmark-pack-loading

build:
	go build $(BUILD_FLAGS) -ldflags "$(LDFLAGS)" -o $(BIN) ./cmd/close-enough

test:
	go test -race ./...

vet:
	go vet ./...

ci: vet test build

benchmark-pre-execution:
	go test -run '^$$' -bench '^BenchmarkPreExecutionLatency$$' -benchmem ./internal/diagnose

benchmark-path-cache:
	go test -run '^$$' -bench '^BenchmarkPATHIndexCache$$' -benchmem ./internal/diagnose

benchmark-pack-loading:
	go test -run '^$$' -bench '^BenchmarkLoadBundledPacks$$' -benchmem ./internal/packs
