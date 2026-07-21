package daemon

import (
	"context"
	"encoding/json"
	"net"
	"testing"
	"time"
)

func FuzzServerMalformedPayloads(f *testing.F) {
	for _, payload := range [][]byte{
		nil,
		[]byte("{"),
		[]byte(`{"version":0,"operation":"status"}`),
		[]byte(`{"version":1,"operation":"unknown"}`),
		[]byte(`{"version":1,"operation":"status"}`),
		[]byte(`{"version":1,"operation":"status","failure_output":"\\u001b"}`),
	} {
		f.Add(payload)
	}
	f.Fuzz(func(t *testing.T, payload []byte) {
		if len(payload) > MaxRequestBytes+1 {
			payload = payload[:MaxRequestBytes+1]
		}
		server, err := NewServer(Endpoint{Network: "pipe", Address: "fuzz"}, func(context.Context, Request) (Response, error) {
			return Response{Version: ProtocolVersion, Action: "none"}, nil
		})
		if err != nil {
			t.Fatal(err)
		}
		serverConnection, clientConnection := net.Pipe()
		done := make(chan struct{})
		go func() {
			server.serveConnection(context.Background(), serverConnection)
			close(done)
		}()
		deadline := time.Now().Add(2 * requestDeadline)
		_ = clientConnection.SetDeadline(deadline)
		_, _ = clientConnection.Write(payload)
		var response Response
		if err := json.NewDecoder(clientConnection).Decode(&response); err == nil {
			if err := response.Validate(); err != nil {
				t.Fatalf("invalid response: %v", err)
			}
		}
		_ = clientConnection.Close()
		select {
		case <-done:
		case <-time.After(requestDeadline):
			t.Fatal("server did not close malformed request connection")
		}
	})
}
