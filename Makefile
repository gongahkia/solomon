.PHONY: all build server run run-server test clean tidy

all: build

build:
	@go build -o bin/monke ./cmd/monke
	@go build -o bin/monke-server ./cmd/monke-server

run:
	@go run ./cmd/monke

run-server:
	@go run ./cmd/monke-server

test:
	@go test ./internal/...

clean:
	@rm -rf bin/

tidy:
	@go mod tidy
