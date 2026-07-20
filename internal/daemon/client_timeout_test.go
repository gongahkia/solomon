//go:build !windows

package daemon

import (
	"context"
	"errors"
	"net"
	"testing"
	"time"
)

func TestClientAppliesConnectionDeadline(t *testing.T) {
	endpoint, err := LocalEndpoint(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen(endpoint.Network, endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	release := make(chan struct{})
	accepted := make(chan struct{})
	go func() {
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		defer connection.Close()
		close(accepted)
		<-release
	}()
	client := Client{Endpoint: endpoint, Timeout: 25 * time.Millisecond}
	start := time.Now()
	_, err = client.Request(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation})
	elapsed := time.Since(start)
	close(release)
	select {
	case <-accepted:
	case <-time.After(time.Second):
		t.Fatal("test listener did not accept the client")
	}
	if !errors.Is(err, ErrUnavailable) || elapsed > time.Second {
		t.Fatalf("Request() = %v after %s", err, elapsed)
	}
}
