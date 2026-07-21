//go:build !windows

package daemon

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func TestListenReplacesStaleUnixSocket(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	fd, err := unix.Socket(unix.AF_UNIX, unix.SOCK_STREAM, 0)
	if err != nil {
		t.Fatal(err)
	}
	if err := unix.Bind(fd, &unix.SockaddrUnix{Name: endpoint.Address}); err != nil {
		unix.Close(fd)
		t.Fatal(err)
	}
	if err := unix.Close(fd); err != nil {
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
}

func TestListenRejectsActiveUnixSocket(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	first, err := NewServer(endpoint, func(context.Context, Request) (Response, error) {
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := first.Listen(); err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go first.Serve(ctx)
	second, err := NewServer(endpoint, func(context.Context, Request) (Response, error) {
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := second.Listen(); !errors.Is(err, ErrAlreadyRunning) {
		t.Fatalf("second Listen() error = %v, want ErrAlreadyRunning", err)
	}
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation})
	if err != nil || response.Action != "none" {
		t.Fatalf("first server response = %#v, %v", response, err)
	}
}
