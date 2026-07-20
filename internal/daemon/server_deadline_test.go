//go:build !windows

package daemon

import (
	"context"
	"encoding/json"
	"net"
	"path/filepath"
	"testing"
	"time"
)

func TestServerAppliesRequestDeadline(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	deadlines := make(chan time.Duration, 1)
	server, err := NewServer(endpoint, func(ctx context.Context, _ Request) (Response, error) {
		deadline, ok := ctx.Deadline()
		if !ok {
			deadlines <- -1
			return Response{Version: ProtocolVersion, Action: "none"}, nil
		}
		deadlines <- time.Until(deadline)
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go server.Serve(ctx)
	connection, err := net.Dial(endpoint.Network, endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if err := json.NewEncoder(connection).Encode(Request{Version: ProtocolVersion, Operation: StatusOperation}); err != nil {
		t.Fatal(err)
	}
	var response Response
	if err := json.NewDecoder(connection).Decode(&response); err != nil {
		t.Fatal(err)
	}
	remaining := <-deadlines
	if remaining <= 0 || remaining > requestDeadline {
		t.Fatalf("request deadline remaining = %s", remaining)
	}
}
