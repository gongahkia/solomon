package diagnose

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/config"
)

func TestCommandTypoProducesHint(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	decision, err := New(Options{Config: config.Default(), Path: dir, CWD: dir}).Check("gti status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Version != AdapterProtocolVersion || decision.Action != "hint" || decision.Suggestion != "git status" || decision.Risk != RiskSafe {
		t.Fatalf("unexpected decision: %#v", decision)
	}
}

func TestRecordCarriesAdapterProtocolVersion(t *testing.T) {
	decision := noDecision()
	fields := strings.Split(strings.TrimSuffix(decision.Record(), "\n"), "\t")
	if len(fields) != 7 || fields[0] != "1" || fields[1] != "none" {
		t.Fatalf("unexpected record: %q", decision.Record())
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

func TestIncompleteInputNeverEmitsRepair(t *testing.T) {
	decision, err := New(Options{Config: config.Default()}).Check("git 'status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "none" || !decision.Incomplete || decision.Suggestion != "" {
		t.Fatalf("unexpected incomplete decision: %#v", decision)
	}
}

func TestTokenizePlainQuotedAndEscapedWords(t *testing.T) {
	words, err := tokenize(`git commit -m "fix bug" path\ with\ spaces ''`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"git", "commit", "-m", "fix bug", "path with spaces", ""}
	if !slices.Equal(words, want) {
		t.Fatalf("words = %#v, want %#v", words, want)
	}
}

func TestTokenizeRejectsIncompleteQuotedAndEscapedInput(t *testing.T) {
	for _, line := range []string{"git 'status", "git status\\"} {
		if _, err := tokenize(line); err == nil {
			t.Fatalf("expected tokenize failure for %q", line)
		}
	}
}

func TestTokenizeSeparatesUnquotedCompoundOperators(t *testing.T) {
	words, err := tokenize(`echo "a|b" && gti status; git sttaus | gti\|literal`)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"echo", "a|b", "&&", "gti", "status", ";", "git", "sttaus", "|", "gti|literal"}
	if !slices.Equal(words, want) {
		t.Fatalf("words = %#v, want %#v", words, want)
	}
}

func TestCommandPositionsResolveCompoundCommandStarts(t *testing.T) {
	words := []string{"MODE=1", "if", "gti", "&&", "echo", "ok", ";", "then", "git", "sttaus", ";", "fi"}
	if got := commandPositions(words); !slices.Equal(got, []int{2, 4, 8}) {
		t.Fatalf("positions = %#v", got)
	}
}

func TestCompoundCommandSuggestionsAndNonCommandArguments(t *testing.T) {
	dir := t.TempDir()
	writeExecutable(t, dir, "git")
	engine := New(Options{Config: config.Default(), Path: dir, CWD: dir})
	decision, err := engine.Check("echo gti && gti status", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "echo gti && git status" {
		t.Fatalf("unexpected command suggestion: %#v", decision)
	}
	decision, err = engine.Check("echo ready; git sttaus", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Suggestion != "echo ready ; git status" {
		t.Fatalf("unexpected semantic suggestion: %#v", decision)
	}
	decision, err = engine.Check("echo gti", "pre")
	if err != nil {
		t.Fatal(err)
	}
	if decision.Action != "none" {
		t.Fatalf("argument was treated as command: %#v", decision)
	}
}

func TestExecutableIndexCachesAndInvalidates(t *testing.T) {
	InvalidateExecutableIndex()
	directory := t.TempDir()
	writeExecutable(t, directory, "git")
	first := executableNames(directory)
	first[0] = "mutated"
	if got := executableNames(directory); !slices.Equal(got, []string{"git"}) {
		t.Fatalf("cached names mutated: %#v", got)
	}
	writeExecutable(t, directory, "go")
	if err := os.Chtimes(directory, time.Now(), time.Now().Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	if got := executableNames(directory); !slices.Equal(got, []string{"git", "go"}) {
		t.Fatalf("directory change was not detected: %#v", got)
	}
	if err := os.Remove(filepath.Join(directory, "go")); err != nil {
		t.Fatal(err)
	}
	InvalidateExecutableIndex()
	if got := executableNames(directory); !slices.Equal(got, []string{"git"}) {
		t.Fatalf("explicit invalidation failed: %#v", got)
	}
}

func TestExecutableCandidateNormalizationAcrossPlatforms(t *testing.T) {
	InvalidateExecutableIndex()
	directory := t.TempDir()
	if err := os.WriteFile(filepath.Join(directory, "Git.EXE"), []byte("binary"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "tool.cmd"), []byte("script"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "README.txt"), []byte("text"), 0o700); err != nil {
		t.Fatal(err)
	}
	if got := executableNamesFor(directory, "windows", ".EXE;.CMD"); !slices.Equal(got, []string{"git", "tool"}) {
		t.Fatalf("windows candidates = %#v", got)
	}
	if !commandExistsFor("GIT.EXE", directory, "windows", ".EXE;.CMD") || !commandExistsFor("git", directory, "windows", ".EXE;.CMD") || commandExistsFor("README.txt", directory, "windows", ".EXE;.CMD") {
		t.Fatal("unexpected Windows candidate matching")
	}
	if got := executableNamesFor(directory, "linux", ""); !slices.Equal(got, []string{"README.txt"}) {
		t.Fatalf("unix candidates = %#v", got)
	}
}

func TestDamerauLevenshteinScoresUnicodeAndTranspositions(t *testing.T) {
	for _, test := range []struct {
		a    string
		b    string
		want int
	}{
		{a: "gti", b: "git", want: 1},
		{a: "café", b: "cafe", want: 1},
		{a: "åb", b: "bå", want: 1},
		{a: "", b: "git", want: 3},
	} {
		if got := damerauLevenshtein(test.a, test.b); got != test.want {
			t.Fatalf("distance(%q, %q) = %d, want %d", test.a, test.b, got, test.want)
		}
	}
}

func TestNearestCandidateUsesDeterministicTieBreaker(t *testing.T) {
	if candidate, distance := nearest("c", []string{"x", "v"}); candidate != "v" || distance != 1 {
		t.Fatalf("nearest = %q, %d", candidate, distance)
	}
	if candidate, distance := nearest("c", nil); candidate != "" || distance != 0 {
		t.Fatalf("empty nearest = %q, %d", candidate, distance)
	}
}

func TestKeyboardAdjacencyBreaksEqualEditDistance(t *testing.T) {
	if adjacent, distant := keyboardAdjacencyDistance("gkt", "git"), keyboardAdjacencyDistance("gkt", "get"); adjacent >= distant {
		t.Fatalf("adjacent score = %d, distant score = %d", adjacent, distant)
	}
	if candidate, distance := nearest("gkt", []string{"get", "git"}); candidate != "git" || distance != 1 {
		t.Fatalf("nearest = %q, %d", candidate, distance)
	}
	if got := keyboardAdjacencyDistance("é", "e"); got != 2 {
		t.Fatalf("non-keyboard score = %d", got)
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
	data, err := json.Marshal(decision.Event("pre"))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) == "" || contains(string(data), "super-secret") || contains(string(data), `"command"`) || contains(decision.Record(), "super-secret") {
		t.Fatalf("secret leaked in diagnostic: %s", data)
	}
}

func TestEventContainsOnlyDiagnosticMetadata(t *testing.T) {
	event := Decision{Version: AdapterProtocolVersion, Action: "hint", Suggestion: "git status", Risk: RiskSafe}.Event("post")
	if event.Stage != "post" || event.Suggestion != "git status" || event.Version != AdapterProtocolVersion {
		t.Fatalf("unexpected event: %#v", event)
	}
	data, err := json.Marshal(event)
	if err != nil {
		t.Fatal(err)
	}
	if contains(string(data), `"command"`) {
		t.Fatalf("event exposes raw command field: %s", data)
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
