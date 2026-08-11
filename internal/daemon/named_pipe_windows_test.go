//go:build windows

package daemon

import (
	"context"
	"sync/atomic"
	"testing"
	"time"
)

func TestWindowsNamedPipeRoundTrip(t *testing.T) {
	endpoint, err := LocalEndpoint(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	server, err := NewServer(endpoint, func(_ context.Context, request Request) (Response, error) {
		calls.Add(1)
		return Response{Version: ProtocolVersion, Action: "hint", Suggestion: request.Command}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- server.Serve(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(time.Second):
			t.Error("named-pipe server did not stop")
		}
	})
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{
		Version:   ProtocolVersion,
		Operation: PreSendOperation,
		Command:   "git sttaus",
	})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || response.Suggestion != "git sttaus" || calls.Load() != 1 {
		t.Fatalf("response = %#v, handler calls = %d", response, calls.Load())
	}
}
