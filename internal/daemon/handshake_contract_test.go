//go:build !windows

package daemon

import (
	"context"
	"path/filepath"
	"testing"
	"time"
)

func TestHandshakeContractOverDaemonSocket(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, (&Service{}).Handle)
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go server.Serve(ctx)
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: HandshakeOperation})
	if err != nil {
		t.Fatal(err)
	}
	if response.Version != ProtocolVersion || response.Action != "ready" {
		t.Fatalf("handshake response = %#v", response)
	}
}
