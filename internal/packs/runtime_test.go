package packs

import (
	"context"
	"errors"
	"testing"
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

func TestRuntimeResolverMatchesTokenizedSubcommandWithSuffix(t *testing.T) {
	resolver, err := NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	match, ok := resolver.MatchWords([]string{"git", "sttaus", "--token=secret"})
	if !ok || match.PackID != "core-git" || match.RuleID != "git-status-sttaus" || match.Suggestion != "git status --token=secret" || match.Original != "sttaus" || match.Replacement != "status" || match.Occurrence != 1 {
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
