//go:build !windows

package daemon

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestListenCreatesPrivateUnixSocket(t *testing.T) {
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
	defer server.listener.Close()
	defer os.Remove(endpoint.Address)
	info, err := os.Stat(endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("socket permissions = %o", info.Mode().Perm())
	}
}
