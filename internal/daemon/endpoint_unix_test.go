//go:build !windows

package daemon

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestLocalEndpointUsesUnixSocket(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	if endpoint.Network != "unix" || !strings.HasSuffix(endpoint.Address, "/daemon.sock") {
		t.Fatalf("endpoint = %#v", endpoint)
	}
}

func TestLocalEndpointFallsBackForLongSocketPath(t *testing.T) {
	directory := filepath.Join(t.TempDir(), strings.Repeat("runtime-", 20))
	endpoint, err := LocalEndpoint(directory)
	if err != nil {
		t.Fatal(err)
	}
	if endpoint.Network != "unix" || len(endpoint.Address) >= 100 || !strings.HasSuffix(endpoint.Address, "/daemon.sock") {
		t.Fatalf("endpoint = %#v", endpoint)
	}
}
