//go:build !windows

package daemon

import (
	"context"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func startDaemonIntegration(t *testing.T, handler Handler) (Endpoint, func()) {
	t.Helper()
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, handler)
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- server.Serve(ctx) }()
	var once sync.Once
	stop := func() {
		once.Do(func() {
			cancel()
			select {
			case err := <-done:
				if err != nil {
					t.Error(err)
				}
			case <-time.After(time.Second):
				t.Error("daemon server did not stop")
			}
		})
	}
	t.Cleanup(stop)
	return endpoint, stop
}
