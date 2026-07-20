//go:build !windows

package daemon

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
)

func TestClientClassifiesUnavailableDaemon(t *testing.T) {
	_, err := (Client{Endpoint: Endpoint{Network: "unix", Address: filepath.Join(t.TempDir(), "missing.sock")}}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation})
	if !errors.Is(err, ErrUnavailable) {
		t.Fatalf("Request() error = %v", err)
	}
}
