package packs

import "testing"

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
