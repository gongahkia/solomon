package daemon

import "testing"

func TestRequestValidation(t *testing.T) {
	if err := (Request{Version: ProtocolVersion, Operation: PreSendOperation, Command: "git sttaus"}).Validate(); err != nil {
		t.Fatalf("Validate() = %v", err)
	}
	if err := (Request{Version: ProtocolVersion + 1, Operation: PreSendOperation}).Validate(); err == nil {
		t.Fatal("Validate() accepted an unsupported version")
	}
	if err := (Request{Version: ProtocolVersion, Operation: "network"}).Validate(); err == nil {
		t.Fatal("Validate() accepted an unknown operation")
	}
	if err := (Request{Version: ProtocolVersion, Operation: PostFailureOperation, FailureOutput: "fatal: missing\n\tat line 1"}).Validate(); err != nil {
		t.Fatalf("Validate() rejected multiline failure output: %v", err)
	}
	if err := (Request{Version: ProtocolVersion, Operation: PostFailureOperation, FailureOutput: "fatal:\x1b]8;;https://example.invalid\a"}).Validate(); err == nil {
		t.Fatal("Validate() accepted terminal control injection")
	}
}

func TestResponseValidation(t *testing.T) {
	if err := (Response{Version: ProtocolVersion, Action: "none"}).Validate(); err != nil {
		t.Fatalf("Validate() = %v", err)
	}
	if err := (Response{Version: ProtocolVersion}).Validate(); err == nil {
		t.Fatal("Validate() accepted an empty action")
	}
	if err := (Response{Version: ProtocolVersion + 1, Action: "none"}).Validate(); err == nil {
		t.Fatal("Validate() accepted an unsupported version")
	}
}
