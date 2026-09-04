package capture

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRelayKeepsOnlyMarkedRedactedOutput(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;Solomon=token\a"}
	relay.Feed("old output\n\x1b]1337;Solomon=token\a")
	relay.Feed("git sttaus\nfatal: TOKEN=top-secret\n")
	got := relay.Snapshot("git sttaus")
	if strings.Contains(got, "top-secret") || strings.Contains(got, "git sttaus") || !strings.Contains(got, "TOKEN=[REDACTED]") {
		t.Fatalf("snapshot = %q", got)
	}
}

func TestRelayRetainsBoundedLatestOutput(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;Solomon=token\a"}
	relay.Feed(relay.marker + strings.Repeat("x", MaxOutputBytes+128))
	if got := len(relay.Snapshot("")); got != MaxOutputBytes {
		t.Fatalf("snapshot length = %d, want %d", got, MaxOutputBytes)
	}
}

func TestRelayHandlesSplitMarker(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;Solomon=token\a"}
	relay.Feed("before\x1b]1337;Solomon=to")
	relay.Feed("ken\aerror: unknown command\n")
	if got := relay.Snapshot(""); got != "error: unknown command" {
		t.Fatalf("snapshot = %q", got)
	}
}

func TestRelayResetDiscardsPreviousCommandOutput(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;Solomon=token\a"}
	relay.Feed(relay.marker + "old error")
	relay.Reset()
	relay.Feed(relay.marker + "new error")
	if got := relay.Snapshot(""); got != "new error" {
		t.Fatalf("snapshot = %q", got)
	}
}

func TestRelayStripsTerminalControlSequences(t *testing.T) {
	relay := &Relay{marker: "\x1b]1337;Solomon=token\a"}
	relay.Feed(relay.marker + "\x1b[31merror\x1b[0m")
	if got := relay.Snapshot(""); got != "error" {
		t.Fatalf("snapshot = %q", got)
	}
}

func TestRelayReadUsesPrivateSocket(t *testing.T) {
	directory, err := os.MkdirTemp("", "ce-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	relay, err := Start(filepath.Join(directory, "relay.sock"), "token")
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	relay.Feed("\x1b]1337;Solomon=token\aerror: command failed")
	got, err := Read(relay.listener.Addr().String(), "")
	if err != nil || got != "error: command failed" {
		t.Fatalf("Read() = %q, %v", got, err)
	}
}

func TestRelaySocketReadDoesNotTreatACommandNamedResetAsAReset(t *testing.T) {
	directory, err := os.MkdirTemp("", "ce-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	relay, err := Start(filepath.Join(directory, "relay.sock"), "token")
	if err != nil {
		t.Fatal(err)
	}
	defer relay.Close()
	relay.Feed("\x1b]1337;Solomon=token\areset\ncommand failed")
	got, err := Read(relay.listener.Addr().String(), "reset")
	if err != nil || got != "command failed" {
		t.Fatalf("Read() = %q, %v", got, err)
	}
}

func TestScriptCanWriteToPrivateFIFO(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("script capture is Unix-only")
	}
	script, err := exec.LookPath("script")
	if err != nil {
		t.Skip("script unavailable")
	}
	mkfifo, err := exec.LookPath("mkfifo")
	if err != nil {
		t.Skip("mkfifo unavailable")
	}
	directory, err := os.MkdirTemp("", "ce-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	fifo := filepath.Join(directory, "output")
	if output, err := exec.Command(mkfifo, "-m", "600", fifo).CombinedOutput(); err != nil {
		t.Fatalf("mkfifo: %v: %s", err, output)
	}
	result := make(chan []byte, 1)
	go func() {
		reader, err := os.Open(fifo)
		if err != nil {
			result <- nil
			return
		}
		defer reader.Close()
		data, _ := io.ReadAll(io.LimitReader(reader, 1024))
		result <- data
	}()
	var command *exec.Cmd
	if runtime.GOOS == "linux" {
		command = exec.Command(script, "-q", "-f", fifo, "-c", "printf capture-probe")
	} else {
		command = exec.Command(script, "-q", fifo, "/bin/sh", "-c", "printf capture-probe")
	}
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("script: %v: %s", err, output)
	}
	if got := string(<-result); !strings.Contains(got, "capture-probe") {
		t.Fatalf("FIFO transcript = %q", got)
	}
}
