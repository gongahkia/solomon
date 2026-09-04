package packs

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/gongahkia/solomon/internal/diagnose"
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

func TestRuntimeResolverPreservesSafeHighRiskTails(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct{ input, want string }{
		{"docker bulid .", "docker build ."},
		{"go buid ./...", "go build ./..."},
		{"cargo buid --release", "cargo build --release"},
	} {
		match, ok := resolver.MatchLine(test.input)
		if !ok || match.Suggestion != test.want || match.Risk != "high" {
			t.Fatalf("MatchLine(%q) = %#v, %t; want %q", test.input, match, ok, test.want)
		}
	}
}

func TestRuntimeResolverRejectsUnsafePreservedTails(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	if match, ok := resolver.MatchWords([]string{"go", "buid", "path with spaces"}); ok {
		t.Fatalf("unsafe tail matched: %#v", match)
	}
}

func TestRuntimeResolverRequiresAnExactRuleMatchForDestructiveSuffixes(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	if match, ok := resolver.MatchLine("git brnach -D solomon-audit-target"); ok {
		t.Fatalf("unsafe suffix matched bundled safe rule: %#v", match)
	}
}

func TestRuntimeResolverExpandsCaptureTemplates(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		input string
		want  string
	}{
		{input: "docker search --stars=5", want: "docker search --filter=stars=5"},
		{input: "helm uninstall solomon", want: "helm status solomon"},
		{input: "aws s3 rm s3://example-bucket --recursive", want: "aws s3 ls s3://example-bucket"},
	} {
		match, ok := resolver.MatchLine(test.input)
		if !ok || match.Suggestion != test.want {
			t.Fatalf("MatchLine(%q) = %#v, %t; want %q", test.input, match, ok, test.want)
		}
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
	first := Pack{SchemaVersion: 1, ID: "alpha", Version: "1.0.0", Publisher: "solomon", Rules: []Rule{{ID: "alpha-rule", Command: "alpha", Pattern: "typo", Replacement: "fixed", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only command"}}}
	second := Pack{SchemaVersion: 1, ID: "beta", Version: "1.0.0", Publisher: "solomon", Rules: []Rule{{ID: "beta-rule", Command: "beta", Pattern: "typo", Replacement: "fixed", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only command"}}}
	for _, pack := range []Pack{second, first} {
		data := []byte(`{"schema_version":1,"id":"` + pack.ID + `","version":"1.0.0","publisher":"solomon","rules":[{"id":"` + pack.ID + `-rule","command":"` + pack.ID + `","pattern":"typo","replacement":"fixed","cause":"typo","risk":"safe","risk_rationale":"read-only command"}]}`)
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
