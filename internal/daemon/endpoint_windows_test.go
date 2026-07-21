//go:build windows

package daemon

import (
	"strings"
	"testing"
)

func TestLocalEndpointUsesRuntimeScopedNamedPipe(t *testing.T) {
	directory := t.TempDir()
	endpoint, err := LocalEndpoint(directory)
	if err != nil {
		t.Fatal(err)
	}
	if endpoint.Network != "npipe" || !strings.HasPrefix(endpoint.Address, `\\.\pipe\close-enough-`) {
		t.Fatalf("endpoint = %#v", endpoint)
	}
	again, err := LocalEndpoint(directory)
	if err != nil || again != endpoint {
		t.Fatalf("same runtime endpoint = %#v, %v", again, err)
	}
	other, err := LocalEndpoint(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if other.Address == endpoint.Address {
		t.Fatalf("runtime directories shared named pipe %q", endpoint.Address)
	}
}
