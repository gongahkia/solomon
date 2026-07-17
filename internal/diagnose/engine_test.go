package diagnose

import (
	"encoding/json"
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

func TestSecretBearingSuggestionIsRedactedAndNeverRewritten(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	cfg := config.Default()
	cfg.Mode = "rewrite"
	decision, err := New(Options{Config: cfg, Path: dir, CWD: dir}).Check("gti --token=super-secret", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action == "rewrite" || decision.Risk != RiskHigh || decision.Suggestion != "git --token=[REDACTED]" {
		t.Fatalf("unsafe decision: %#v", decision)
	}
	data, err := json.Marshal(decision)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) == "" || contains(string(data), "super-secret") || contains(decision.Record(), "super-secret") {
		t.Fatalf("secret leaked in diagnostic: %s", data)
	}
}

func contains(value, substring string) bool {
	for index := 0; index+len(substring) <= len(value); index++ {
		if value[index:index+len(substring)] == substring {
			return true
		}
	}
	return false
}

func writeExecutable(t *testing.T, dir, name string) {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"), 0o700); err != nil {
		t.Fatal(err)
	}
}
