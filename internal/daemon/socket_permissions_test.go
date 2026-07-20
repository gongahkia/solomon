//go:build !windows

package daemon

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestUnixSocketPermissionsSurviveRequest(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, func(context.Context, Request) (Response, error) {
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	go server.Serve(context.Background())
	if _, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation}); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("socket permissions = %o", info.Mode().Perm())
	}
}
