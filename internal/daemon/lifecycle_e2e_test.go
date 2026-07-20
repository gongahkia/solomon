//go:build !windows

package daemon

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestDaemonLifecycleStartStatusStop(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, func(_ context.Context, request Request) (Response, error) {
		switch request.Operation {
		case StatusOperation:
			return Response{Version: ProtocolVersion, Action: "ready"}, nil
		case StopOperation:
			return Response{Version: ProtocolVersion, Action: "stopping"}, nil
		default:
			return Response{Version: ProtocolVersion, Action: "none"}, nil
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- server.Serve(context.Background()) }()
	client := Client{Endpoint: endpoint, Timeout: time.Second}
	status, err := client.Request(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation})
	if err != nil || status.Action != "ready" {
		t.Fatalf("status = %#v, %v", status, err)
	}
	stop, err := client.Request(context.Background(), Request{Version: ProtocolVersion, Operation: StopOperation})
	if err != nil || stop.Action != "stopping" {
		t.Fatalf("stop = %#v, %v", stop, err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("server did not stop")
	}
	if _, err := os.Lstat(endpoint.Address); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("socket still exists: %v", err)
	}
}
