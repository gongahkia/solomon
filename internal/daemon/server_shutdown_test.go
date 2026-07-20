//go:build !windows

package daemon

import (
	"context"
	"path/filepath"
	"testing"
	"time"
)

func TestStopRequestClosesServer(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, func(_ context.Context, request Request) (Response, error) {
		if request.Operation == StopOperation {
			return Response{Version: ProtocolVersion, Action: "stopping"}, nil
		}
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- server.Serve(context.Background()) }()
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: StopOperation})
	if err != nil || response.Action != "stopping" {
		t.Fatalf("stop response = %+v, %v", response, err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("server did not stop")
	}
}
