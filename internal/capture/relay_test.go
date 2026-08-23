package capture

import (
	"strings"
	"testing"
)

func TestRelayKeepsOnlyMarkedRedactedOutput(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;CloseEnough=token\a"}
	relay.Feed("old output\n\x1b]1337;CloseEnough=token\a")
	relay.Feed("git sttaus\nfatal: TOKEN=top-secret\n")
	got := relay.Snapshot("git sttaus")
	if strings.Contains(got, "top-secret") || strings.Contains(got, "git sttaus") || !strings.Contains(got, "TOKEN=[REDACTED]") {
		t.Fatalf("snapshot = %q", got)
	}
}

func TestRelayRetainsBoundedLatestOutput(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;CloseEnough=token\a"}
	relay.Feed(relay.marker + strings.Repeat("x", MaxOutputBytes+128))
	if got := len(relay.Snapshot("")); got != MaxOutputBytes {
		t.Fatalf("snapshot length = %d, want %d", got, MaxOutputBytes)
	}
}

func TestRelayHandlesSplitMarker(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;CloseEnough=token\a"}
	relay.Feed("before\x1b]1337;CloseEnough=to")
	relay.Feed("ken\aerror: unknown command\n")
	if got := relay.Snapshot(""); got != "error: unknown command" {
		t.Fatalf("snapshot = %q", got)
	}
}
