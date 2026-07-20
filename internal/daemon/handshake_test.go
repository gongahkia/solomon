package daemon

import (
	"context"
	"testing"
)

func TestServiceReturnsReadyForHandshake(t *testing.T) {
	service := Service{}
	response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: HandshakeOperation})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "ready" {
		t.Fatalf("response = %+v", response)
	}
}
