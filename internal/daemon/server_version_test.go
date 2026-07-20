//go:build !windows

package daemon

import (
	"context"
	"encoding/json"
	"net"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

func TestServerRejectsUnsupportedProtocolVersion(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	server, err := NewServer(endpoint, func(context.Context, Request) (Response, error) {
		calls.Add(1)
		return Response{Version: ProtocolVersion, Action: "none"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Listen(); err != nil {
		t.Fatal(err)
	}
	defer server.Close()
	go server.Serve(context.Background())
	connection, err := net.Dial(endpoint.Network, endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if err := json.NewEncoder(connection).Encode(Request{Version: ProtocolVersion + 1, Operation: StatusOperation}); err != nil {
		t.Fatal(err)
	}
	var response Response
	if err := json.NewDecoder(connection).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response.Action != "none" || !strings.Contains(response.Error, "unsupported daemon protocol version") || calls.Load() != 0 {
		t.Fatalf("response = %#v, handler calls = %d", response, calls.Load())
	}
}
