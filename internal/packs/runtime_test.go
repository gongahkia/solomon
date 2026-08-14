package packs

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

func TestRuntimeResolverMatchesBundledRule(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	match, ok := resolver.MatchLine("git sttaus")
	if !ok {
		t.Fatal("MatchLine() did not match")
	}
	if match.PackID != "core-git" || match.RuleID != "git-status-sttaus" || match.Suggestion != "git status" || match.Risk != "safe" {
		t.Fatalf("match = %#v", match)
	}
}

func TestRuntimeResolverRejectsUnclassifiedSuffix(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	match, ok := resolver.MatchWords([]string{"git", "sttaus", "--token=secret"})
	if ok {
		t.Fatalf("match = %#v, ok = %t", match, ok)
	}
}

func TestRuntimeResolverPropagatesCancellation(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, _, err := resolver.MatchWordsContext(ctx, []string{"git", "sttaus"}); !errors.Is(err, context.Canceled) {
		t.Fatalf("MatchWordsContext cancellation error = %v", err)
	}
}

func TestRuntimeResolverRejectsComplexShellSyntax(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	for _, line := range []string{"git 'sttaus'", "git sttaus && echo unsafe", " git sttaus", "git sttaus "} {
		if _, ok := resolver.MatchLine(line); ok {
			t.Fatalf("MatchLine(%q) unexpectedly matched", line)
		}
	}
}

func TestLoadInstalledIsDeterministicAndRejectsUnsafeEntries(t *testing.T) {
	directory := t.TempDir()
	first := Pack{SchemaVersion: 1, ID: "alpha", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "alpha-rule", Command: "alpha", Pattern: "typo", Replacement: "fixed", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only command"}}}
	second := Pack{SchemaVersion: 1, ID: "beta", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "beta-rule", Command: "beta", Pattern: "typo", Replacement: "fixed", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only command"}}}
	for _, pack := range []Pack{second, first} {
		data := []byte(`{"schema_version":1,"id":"` + pack.ID + `","version":"1.0.0","publisher":"close-enough","rules":[{"id":"` + pack.ID + `-rule","command":"` + pack.ID + `","pattern":"typo","replacement":"fixed","cause":"typo","risk":"safe","risk_rationale":"read-only command"}]}`)
		if err := os.WriteFile(filepath.Join(directory, installedPackName(pack)), data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	loaded, err := LoadInstalled(directory)
	if err != nil || len(loaded) != 2 || loaded[0].ID != "alpha" || loaded[1].ID != "beta" {
		t.Fatalf("installed packs = %#v, %v", loaded, err)
	}
	if err := os.WriteFile(filepath.Join(directory, "not-a-pack.json"), []byte(`{}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadInstalled(directory); err == nil {
		t.Fatal("accepted a non-canonical installed pack name")
	}
}
