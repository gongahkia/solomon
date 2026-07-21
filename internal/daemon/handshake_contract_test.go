//go:build !windows

package daemon

import (
	"context"
	"testing"
	"time"
)

func TestHandshakeContractOverDaemonSocket(t *testing.T) {
	endpoint, _ := startDaemonIntegration(t, (&Service{}).Handle)
	response, err := (Client{Endpoint: endpoint, Timeout: time.Second}).Request(context.Background(), Request{Version: ProtocolVersion, Operation: HandshakeOperation})
	if err != nil {
		t.Fatal(err)
	}
	if response.Version != ProtocolVersion || response.Action != "ready" {
		t.Fatalf("handshake response = %#v", response)
	}
}
