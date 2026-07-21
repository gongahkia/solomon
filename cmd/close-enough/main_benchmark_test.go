package main

import (
	"context"
	"errors"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/gongahkia/close-enough/internal/daemon"
)

func BenchmarkRequestDaemonColdStartFailOpen(b *testing.B) {
	if runtime.GOOS == "windows" {
		b.Skip("Windows named-pipe transport is tracked separately")
	}
	endpoint, err := daemon.LocalEndpoint(filepath.Join(b.TempDir(), "runtime"))
	if err != nil {
		b.Fatal(err)
	}
	original := startDaemonProcess
	startDaemonProcess = func() error { return errors.New("daemon start failed") }
	b.Cleanup(func() { startDaemonProcess = original })
	request := daemon.Request{Version: daemon.ProtocolVersion, Operation: daemon.HandshakeOperation}
	b.ResetTimer()
	for range b.N {
		_, err := requestDaemon(context.Background(), endpoint, request, true)
		if !errors.Is(err, daemon.ErrUnavailable) {
			b.Fatalf("requestDaemon() error = %v", err)
		}
	}
}
