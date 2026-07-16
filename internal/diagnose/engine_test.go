package diagnose

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
)

func TestCommandTypoProducesHint(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	decision, err := New(Options{Config: config.Default(), Path: dir, CWD: dir}).Check("gti status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "hint" || decision.Suggestion != "git status" || decision.Risk != RiskSafe {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestGitSubcommandTypo(t *testing.T) {
	decision, err := New(Options{Config: config.Default()}).Check("git sttaus", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "git status" || decision.Cause != "unknown Git subcommand" {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestRewriteNeedsVeryHighConfidence(t *testing.T) {
	cfg := config.Default()
	cfg.Mode = "rewrite"
	decision, err := New(Options{Config: cfg}).Check("git statsu", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "rewrite" {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestHighRiskNeverAutoApplied(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "rm")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	cfg.AutoApplySafe = true
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("rmm -rf .", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action == "rewrite" || decision.Risk != RiskHigh {
		t.Fatalf("unsafe decision: %#v", decision)
	}
}

func TestIncompleteInputFails(t *testing.T) {
	_, err := New(Options{Config: config.Default()}).Check("git 'status", "pre")
	if err == nil {
		t.Fatal("expected error")
	}
}

func writeExecutable(t *testing.T, dir, name string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o700); err != nil {
		t.Fatal(err)
	}
}
