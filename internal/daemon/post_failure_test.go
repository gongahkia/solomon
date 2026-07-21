package daemon

import (
	"context"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/localstate"
)

func TestServiceAcceptsPostFailureEvent(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := &Service{Config: cfg, Store: store, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Session: "shell", Command: "git sttaus", FailureOutput: "fatal: failed"}); err != nil {
		t.Fatal(err)
	}
	service.mu.Lock()
	pending, ok := service.failures[failureKey("shell", "")]
	service.mu.Unlock()
	if !ok || pending.command != "git sttaus" || pending.output != "fatal: failed" {
		t.Fatalf("pending failure = %#v, exists = %t", pending, ok)
	}
}

func TestServiceCapsPostFailureOutput(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := &Service{Config: cfg, Store: store, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	output := strings.Repeat("x", maxFailureOutputBytes+1)
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Session: "shell", Command: "git sttaus", FailureOutput: output}); err != nil {
		t.Fatal(err)
	}
	service.mu.Lock()
	pending := service.failures[failureKey("shell", "")]
	service.mu.Unlock()
	if len(pending.output) != maxFailureOutputBytes {
		t.Fatalf("failure output length = %d, want %d", len(pending.output), maxFailureOutputBytes)
	}
}

func TestServiceRedactsPostFailureOutputBeforePersistence(t *testing.T) {
	store, err := localstate.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	cfg := config.Default()
	cfg.LocalLearningEnabled = true
	service := &Service{Config: cfg, Store: store, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	if _, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PostFailureOperation, Session: "shell", Command: "git sttaus", FailureOutput: "fatal: TOKEN=top-secret"}); err != nil {
		t.Fatal(err)
	}
	service.mu.Lock()
	pending := service.failures[failureKey("shell", "")]
	service.mu.Unlock()
	if pending.output != "fatal: TOKEN=[REDACTED]" || strings.Contains(pending.output, "top-secret") {
		t.Fatalf("persisted failure output = %q", pending.output)
	}
}
