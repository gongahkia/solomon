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

func TestServerAcceptsAndHandlesRequest(t *testing.T) {
	endpoint, err := LocalEndpoint(filepath.Join(t.TempDir(), "runtime"))
	if err != nil {
		t.Fatal(err)
	}
	server, err := NewServer(endpoint, func(_ context.Context, request Request) (Response, error) {
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
	connection, err := net.Dial(endpoint.Network, endpoint.Address)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if err := json.NewEncoder(connection).Encode(Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"}); err != nil {
		t.Fatal(err)
	}
	var response Response
	if err := json.NewDecoder(connection).Decode(&response); err != nil {
		t.Fatal(err)
	}
	if response.Action != "hint" || response.Suggestion != "git sttaus" {
		t.Fatalf("response = %#v", response)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("server did not stop")
	}
}
