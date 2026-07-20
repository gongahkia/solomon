package daemon

import (
	"context"
	"os"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
)

func BenchmarkWarmCuratedPreSend(b *testing.B) {
	if os.PathSeparator == '\\' {
		b.Skip("Windows named-pipe transport is tracked separately")
	}
	endpoint, err := LocalEndpoint(b.TempDir())
	if err != nil {
		b.Fatal(err)
	}
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		b.Fatal(err)
	}
	cfg := config.Default()
	service := &Service{Config: cfg, Packs: resolver, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: b.TempDir(), CWD: b.TempDir()})}
	server, err := NewServer(endpoint, service.Handle)
	if err != nil {
		b.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		b.Fatal(err)
	}
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go server.Serve(ctx)
	client := Client{Endpoint: endpoint}
	request := Request{Version: ProtocolVersion, Operation: PreSendOperation, Shell: "zsh", Session: "benchmark", Command: "git sttaus"}
	b.ResetTimer()
	for range b.N {
		response, err := client.Request(context.Background(), request)
		if err != nil || response.Action != "rewrite" {
			b.Fatalf("Request() = %+v, %v", response, err)
		}
	}
}
