package daemon

import (
	"context"
	"testing"
)

func TestServiceReturnsReadyForStatus(t *testing.T) {
	response, err := (&Service{}).Handle(context.Background(), Request{Version: ProtocolVersion, Operation: StatusOperation})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "ready" {
		t.Fatalf("response = %+v", response)
	}
}
