package daemon

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
)

func TestDaemonCoreGitCorpus(t *testing.T) {
	testDaemonPackCorpus(t, "core-git.json", []string{"git-subcommand-typos", "git-flag-repairs", "git-path-repairs", "git-conceptual-misuse"})
}

func TestDaemonPackageManagerCorpus(t *testing.T) {
	testDaemonPackCorpus(t, "package-managers.json", []string{"package-manager-subcommand-typos", "package-manager-flag-repairs", "package-manager-path-repairs", "package-manager-conceptual-misuse"})
}

func TestDaemonLanguagePackCorpora(t *testing.T) {
	for _, test := range []struct {
		name    string
		pack    string
		corpora []string
	}{
		{name: "javascript", pack: "javascript.json", corpora: []string{"javascript-subcommand-typos", "javascript-flag-repairs", "javascript-path-repairs", "javascript-conceptual-misuse"}},
		{name: "python", pack: "python.json", corpora: []string{"python-subcommand-typos", "python-flag-repairs", "python-path-repairs", "python-conceptual-misuse"}},
		{name: "rust", pack: "rust.json", corpora: []string{"rust-subcommand-typos", "rust-flag-repairs", "rust-path-repairs", "rust-conceptual-misuse"}},
	} {
		t.Run(test.name, func(t *testing.T) { testDaemonPackCorpus(t, test.pack, test.corpora) })
	}
}

func TestDaemonSystemsPackCorpora(t *testing.T) {
	for _, test := range []struct {
		name    string
		pack    string
		corpora []string
	}{
		{name: "go", pack: "go.json", corpora: []string{"go-subcommand-typos", "go-flag-repairs", "go-path-repairs", "go-conceptual-misuse"}},
		{name: "containers", pack: "containers.json", corpora: []string{"containers-subcommand-typos", "containers-flag-repairs", "containers-path-repairs", "containers-conceptual-misuse"}},
		{name: "kubernetes-cloud", pack: "kubernetes-cloud.json", corpora: []string{"kubernetes-cloud-subcommand-typos", "kubernetes-cloud-flag-repairs", "kubernetes-cloud-path-repairs", "kubernetes-cloud-conceptual-misuse"}},
	} {
		t.Run(test.name, func(t *testing.T) { testDaemonPackCorpus(t, test.pack, test.corpora) })
	}
}

func testDaemonPackCorpus(t *testing.T, packName string, corpusNames []string) {
	t.Helper()
	pack, err := packs.Load(filepath.Join("..", "..", "packs", packName))
	if err != nil {
		t.Fatal(err)
	}
	resolver, err := packs.NewBundledRuntimeResolver()
	if err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	service := Service{Config: cfg, Packs: resolver, Engine: diagnose.New(diagnose.Options{Config: cfg, Path: t.TempDir(), CWD: t.TempDir()})}
	rules := make(map[string]packs.Rule, len(pack.Rules))
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	seen := make(map[string]struct{}, len(rules))
	for _, name := range corpusNames {
		corpus, err := packs.LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", name))
		if err != nil {
			t.Fatal(err)
		}
		for _, fixture := range corpus {
			for _, test := range fixture.Cases {
				t.Run(test.ID, func(t *testing.T) {
					rule, ok := rules[test.RuleID]
					if !ok {
						t.Fatalf("fixture references missing rule %q", test.RuleID)
					}
					response, err := service.Handle(context.Background(), Request{Version: ProtocolVersion, Operation: PreSendOperation, Session: test.ID, Command: test.Command + " " + test.Input})
					if err != nil {
						t.Fatal(err)
					}
					wantAction := "hint"
					if rule.Risk == diagnose.RiskSafe {
						wantAction = "rewrite"
					} else if rule.Risk == diagnose.RiskHigh {
						wantAction = "interrupt"
					}
					if response.Action != wantAction || response.PackID != pack.ID || response.RuleID != rule.ID {
						t.Fatalf("response = %#v", response)
					}
					seen[rule.ID] = struct{}{}
				})
			}
		}
	}
	for _, rule := range pack.Rules {
		if _, ok := seen[rule.ID]; !ok {
			t.Errorf("rule %q has no daemon corpus case", rule.ID)
		}
	}
}
