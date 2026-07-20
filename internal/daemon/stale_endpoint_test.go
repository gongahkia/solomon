//go:build !windows

package daemon

import (
	"context"
	"path/filepath"
	"testing"

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
