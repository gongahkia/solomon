package daemon

import (
	"context"
	"testing"
)

func TestServiceStopsOnStopRequest(t *testing.T) {
	response, err := (&Service{}).Handle(context.Background(), Request{Version: ProtocolVersion, Operation: StopOperation})
	if err != nil {
		t.Fatal(err)
	}
	if response.Action != "stopping" {
		t.Fatalf("response = %+v", response)
	}
}
