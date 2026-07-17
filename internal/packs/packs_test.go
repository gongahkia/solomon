package packs

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

func TestValidatePack(t *testing.T) {
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "^sttaus$", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	if err := pack.Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestSchemaCompatibilityPolicyRejectsLegacyAndFutureVersions(t *testing.T) {
	for _, test := range []struct {
		version int
		valid   bool
	}{
		{SchemaVersionV1 - 1, false},
		{SchemaVersionV1, true},
		{SchemaVersionV1 + 1, false},
	} {
		compatibility := SchemaCompatibility(test.version)
		if compatibility.SchemaVersion != test.version || compatibility.Compatible != test.valid || (ValidateSchemaCompatibility(test.version) == nil) != test.valid {
			t.Fatalf("schema compatibility = %#v for version %d", compatibility, test.version)
		}
	}
}

func TestRejectUnknownManifestField(t *testing.T) {
	path := t.TempDir() + "/pack.json"
	data := []byte(`{"schema_version":1,"id":"core","version":"1","publisher":"close-enough","rules":[{"id":"ok","command":"git","pattern":"x","replacement":"y","cause":"z","risk":"safe"}],"unknown":true}`)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("expected unknown field failure")
	}
}

func TestLoadRejectsNestedUnknownFieldsAndTrailingJSON(t *testing.T) {
	path := t.TempDir() + "/pack.json"
	for _, data := range [][]byte{
		[]byte(`{"schema_version":1,"id":"core","version":"1","publisher":"close-enough","rules":[{"id":"ok","command":"git","pattern":"x","replacement":"y","cause":"z","risk":"safe","unknown":true}]}`),
		[]byte(`{"schema_version":1,"id":"core","version":"1","publisher":"close-enough","rules":[{"id":"ok","command":"git","pattern":"x","replacement":"y","cause":"z","risk":"safe"}]} {}`),
	} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := Load(path); err == nil {
			t.Fatalf("accepted invalid manifest %s", data)
		}
	}
}

func TestRejectInvalidPattern(t *testing.T) {
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "bad", Command: "git", Pattern: "[", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	if err := pack.Validate(); err == nil {
		t.Fatal("expected error")
	}
}

func TestIdentifierAndSemanticVersionValidation(t *testing.T) {
	for _, value := range []string{"core", "core-git", "rule-2"} {
		if !identifier(value) {
			t.Fatalf("rejected valid identifier %q", value)
		}
	}
	for _, value := range []string{"Core", "core_git", "core-", "core--git", "../core"} {
		if identifier(value) {
			t.Fatalf("accepted invalid identifier %q", value)
		}
	}
	for _, value := range []string{"1.0.0", "0.1.0-alpha.1", "1.2.3+build.7"} {
		if !semanticVersion(value) {
			t.Fatalf("rejected valid semantic version %q", value)
		}
	}
	for _, value := range []string{"1", "1.0", "01.0.0", "1.0.0-01", "1.0.0+"} {
		if semanticVersion(value) {
			t.Fatalf("accepted invalid semantic version %q", value)
		}
	}
	base := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	for _, mutate := range []func(*Pack){
		func(pack *Pack) { pack.ID = "Core" },
		func(pack *Pack) { pack.Version = "1" },
		func(pack *Pack) { pack.Publisher = "close_enough" },
		func(pack *Pack) { pack.Rules[0].ID = "rule_1" },
	} {
		pack := base
		mutate(&pack)
		if err := pack.Validate(); err == nil {
			t.Fatalf("accepted invalid pack %#v", pack)
		}
	}
}

func TestCompileMatchesDeclarativeRulesWithoutEvaluation(t *testing.T) {
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: `^sttaus$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	compiled, err := Compile(pack)
	if err != nil {
		t.Fatal(err)
	}
	if rule, ok := compiled.Match("git", "sttaus"); !ok || rule.ID != "git-status" {
		t.Fatalf("compiled match = %#v, %t", rule, ok)
	}
	if _, ok := compiled.Match("sh", "sttaus"); ok {
		t.Fatal("matcher ignored declared command")
	}
	marker := t.TempDir() + "/marker"
	injection := Pack{SchemaVersion: SchemaVersionV1, ID: "literal", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "literal-text", Command: "git", Pattern: `^\$\(touch .+\)$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "literal input match"}}}
	compiled, err = Compile(injection)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := compiled.Match("git", "$(touch "+marker+")"); !ok {
		t.Fatal("literal matcher did not match")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("matcher executed input: %v", err)
	}
}

func TestTransformationTemplateValidation(t *testing.T) {
	for _, test := range []struct {
		pattern     string
		replacement string
		valid       bool
	}{
		{`^(git) (sttaus)$`, `$1 status`, true},
		{`^sttaus$`, `status $$HOME`, true},
		{`^(git)$`, `$2`, false},
		{`^sttaus$`, `${command}`, false},
		{`^sttaus$`, `$(touch marker)`, false},
		{`^sttaus$`, `status$`, false},
	} {
		pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: test.pattern, Replacement: test.replacement, Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
		if got := pack.Validate() == nil; got != test.valid {
			t.Fatalf("template %q with %q valid = %t, want %t", test.pattern, test.replacement, got, test.valid)
		}
	}
}

func TestExplanationTemplateValidation(t *testing.T) {
	for _, test := range []struct {
		cause string
		valid bool
	}{
		{"unknown subcommand $1", true},
		{"unsafe\x1b[31m", false},
		{"$(touch marker)", false},
		{string(make([]byte, 513)), false},
	} {
		pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: `^(sttaus)$`, Replacement: "status", Cause: test.cause, Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
		if got := pack.Validate() == nil; got != test.valid {
			t.Fatalf("explanation %q valid = %t, want %t", test.cause, got, test.valid)
		}
	}
}

func TestRiskMetadataValidation(t *testing.T) {
	for _, test := range []struct {
		risk      diagnose.Risk
		rationale string
		valid     bool
	}{
		{diagnose.RiskSafe, "read-only status query", true},
		{diagnose.RiskHigh, "may modify remote state", true},
		{diagnose.RiskUnknown, "cannot classify operation", true},
		{diagnose.RiskSafe, "", false},
		{diagnose.Risk("invalid"), "unknown", false},
		{diagnose.RiskHigh, "unsafe\nreason", false},
	} {
		pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: "typo", Risk: test.risk, RiskRationale: test.rationale}}}
		if got := pack.Validate() == nil; got != test.valid {
			t.Fatalf("risk metadata %#v valid = %t, want %t", test, got, test.valid)
		}
	}
}

func TestFixtureLoadAndRun(t *testing.T) {
	path := t.TempDir() + "/fixture.json"
	data := []byte(`{"schema_version":1,"cases":[{"id":"typo","command":"git","input":"sttaus","rule_id":"git-status"},{"id":"no-match","command":"git","input":"log"}]}`)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	fixture, err := LoadFixture(path)
	if err != nil {
		t.Fatal(err)
	}
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: `^sttaus$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	if err := RunFixture(pack, fixture); err != nil {
		t.Fatal(err)
	}
	fixture.Cases[0].RuleID = "missing"
	if err := RunFixture(pack, fixture); err == nil {
		t.Fatal("expected fixture mismatch")
	}
}

func TestFixtureRejectsUnknownAndInvalidSchemas(t *testing.T) {
	path := t.TempDir() + "/fixture.json"
	for _, data := range [][]byte{
		[]byte(`{"schema_version":1,"cases":[{"id":"case","command":"git","input":"status","unknown":true}]}`),
		[]byte(`{"schema_version":2,"cases":[{"id":"case","command":"git","input":"status"}]}`),
	} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		fixture, err := LoadFixture(path)
		if err == nil && fixture.Validate() == nil {
			t.Fatalf("accepted invalid fixture %s", data)
		}
	}
}

func TestFixtureCorpusLoadAndRun(t *testing.T) {
	directory := t.TempDir()
	fixtures := map[string]string{
		"zeta.json":  `{"schema_version":1,"cases":[{"id":"zeta","command":"git","input":"log"}]}`,
		"alpha.json": `{"schema_version":1,"cases":[{"id":"alpha","command":"git","input":"sttaus","rule_id":"git-status"}]}`,
	}
	for name, data := range fixtures {
		if err := os.WriteFile(filepath.Join(directory, name), []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	corpus, err := LoadFixtureCorpus(directory)
	if err != nil {
		t.Fatal(err)
	}
	if len(corpus) != 2 || corpus[0].Cases[0].ID != "alpha" {
		t.Fatalf("corpus = %#v", corpus)
	}
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: `^sttaus$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched fixture corpus")
	}
	if err := os.WriteFile(filepath.Join(directory, "invalid.json"), []byte(`{"schema_version":1,"cases":[{"id":"bad","command":"git","unknown":true}]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadFixtureCorpus(directory); err == nil {
		t.Fatal("accepted invalid fixture corpus")
	}
}

func TestCommandCandidateCorpusLoadAndRun(t *testing.T) {
	path := filepath.Join(t.TempDir(), "candidates.json")
	data := []byte(`{"schema_version":1,"candidates":[{"id":"git-command-gti","command":"gti","replacement":"git"}]}`)
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadCommandCandidateCorpus(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		return map[string]string{"gti": "git"}[command], command == "gti"
	}); err != nil {
		t.Fatal(err)
	}
	if err := RunCommandCandidateCorpus(corpus, func(string) (string, bool) { return "", false }); err == nil {
		t.Fatal("accepted unresolved command candidate")
	}
	if err := os.WriteFile(path, []byte(`{"schema_version":1,"candidates":[{"id":"git-command-gti","command":"gti","replacement":"git","unknown":true}]}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadCommandCandidateCorpus(path); err == nil {
		t.Fatal("accepted invalid command candidate corpus")
	}
}

func TestGitCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "git-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(corpus.Candidates) != 3 || corpus.Candidates[0].Command != "gti" || corpus.Candidates[0].Replacement != "git" {
		t.Fatalf("git command candidates = %#v", corpus)
	}
}

func TestPackageManagerCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"npn": "npm", "pnmp": "pnpm", "yarnn": "yarn", "breww": "brew", "cargoa": "cargo"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "npn")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err == nil {
		t.Fatal("accepted incomplete package manager candidates")
	}
}

func TestJavaScriptCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"ndoe": "node", "npxx": "npx", "denoo": "deno", "bnu": "bun", "tsn": "ts-node"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "ndoe")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err == nil {
		t.Fatal("accepted incomplete JavaScript candidates")
	}
}

func TestPythonCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "python-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"pyhton": "python", "pip3p": "pip3", "pytestt": "pytest", "pyhton3": "python3", "uvv": "uv"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "pyhton")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) {
		value, ok := resolved[command]
		return value, ok
	}); err == nil {
		t.Fatal("accepted incomplete Python candidates")
	}
}

func TestRustCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"cagro": "cargo", "rustcc": "rustc", "rustupp": "rustup", "cargo-fmt": "cargo", "clippyy": "clippy"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "cagro")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err == nil {
		t.Fatal("accepted incomplete Rust candidates")
	}
}

func TestGoCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "go-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"goo": "go", "ggo": "go", "gol": "go", "gofm": "gofmt", "gofmtt": "gofmt"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "goo")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err == nil {
		t.Fatal("accepted incomplete Go candidates")
	}
}

func TestContainersCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"dockre": "docker", "dokcer": "docker", "podmna": "podman", "docker-comopse": "docker-compose", "docker-composee": "docker-compose"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "dockre")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err == nil {
		t.Fatal("accepted incomplete container candidates")
	}
}

func TestKubernetesCloudCommandNameCandidateCorpus(t *testing.T) {
	corpus, err := LoadCommandCandidateCorpus(filepath.Join("..", "..", "packs", "corpus", "kubernetes-cloud-command-name.json"))
	if err != nil {
		t.Fatal(err)
	}
	resolved := map[string]string{"kubctl": "kubectl", "kubectll": "kubectl", "helmm": "helm", "terrafom": "terraform", "awss": "aws", "gclodu": "gcloud"}
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err != nil {
		t.Fatal(err)
	}
	delete(resolved, "kubctl")
	if err := RunCommandCandidateCorpus(corpus, func(command string) (string, bool) { value, ok := resolved[command]; return value, ok }); err == nil {
		t.Fatal("accepted incomplete Kubernetes/cloud candidates")
	}
}

func TestContainersSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "containers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled container pack = %#v", bundledPack)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"docker-build-bulid", "docker-run-runn", "docker-push-puch", "podman-build-bulid", "docker-compose-up-upp"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched container corpus")
	}
}

func TestContainersFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "containers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	if risk["docker-search-stars"] != diagnose.RiskSafe || risk["docker-search-automated"] != diagnose.RiskSafe {
		t.Fatalf("container search flag risks = %#v", risk)
	}
	for _, id := range []string{"docker-run-detachd", "docker-build-no-cachee", "docker-compose-dryrun"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched container flag corpus")
	}
}

func TestContainersPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "containers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"docker-build-dockerfil", "docker-compose-file-yamll", "docker-compose-legacy-file-yamll"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched container path corpus")
	}
}

func TestContainersConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "containers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"docker-system-prune", "docker-system-prune-all-volumes", "docker-compose-down-volumes", "docker-run-privileged", "docker-rm-force", "docker-compose-up"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched container conceptual corpus")
	}
}

func TestGoSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "go.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "go-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled Go pack = %#v", bundledPack)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"go-build-buid", "go-test-tes", "go-install-instal", "go-get-gett"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Go corpus")
	}
}

func TestGoFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "go.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "go-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"go-test-count-counnt", "go-build-mod-readony", "gofmt-write-ww", "go-get-download-d"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Go flag corpus")
	}
}

func TestGoPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "go.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "go-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"go-run-package-mian", "go-test-package-pakcs", "go-build-modfile-mdo", "go-test-modfile-mdo"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Go path corpus")
	}
}

func TestGoConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "go.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "go-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"go-clean", "go-run", "go-generate", "go-mod-tidy", "gofmt-write"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Go conceptual corpus")
	}
}

func TestRustSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "rust.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled Rust pack = %#v", bundledPack)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"cargo-build-buid", "cargo-test-tes", "cargo-publish-pubish", "rustup-update-updat"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Rust corpus")
	}
}

func TestRustFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "rust.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	if risk["cargo-version-verison"] != diagnose.RiskSafe || risk["cargo-build-release"] != diagnose.RiskHigh || risk["cargo-check-all"] != diagnose.RiskHigh {
		t.Fatalf("Rust flag risks = %#v", risk)
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Rust flag corpus")
	}
}

func TestRustPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "rust.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"cargo-build-manifest-tmol", "cargo-test-manifest-tmol", "rustc-source-mian"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Rust path corpus")
	}
}

func TestRustConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "rust.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"cargo-publish", "cargo-clean", "cargo-run", "rustup-update"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Rust conceptual corpus")
	}
}

func TestPythonSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "python.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "python-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled Python pack = %#v", bundledPack)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"python-pip-install-instal", "python-venv-venvv", "pip-install-instal", "uv-run-rnu"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Python corpus")
	}
}

func TestPythonFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "python.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "python-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	if risk["python-version-verison"] != diagnose.RiskSafe || risk["pip-install-no-dep"] != diagnose.RiskHigh || risk["pip-install-2020-resolver"] != diagnose.RiskHigh {
		t.Fatalf("Python flag risks = %#v", risk)
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Python flag corpus")
	}
}

func TestPythonPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "python.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "python-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"python-entrypoint-maine", "pytest-tests-test", "pip-install-requiremnts", "uv-run-project-projet"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Python path corpus")
	}
}

func TestPythonConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "python.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "python-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"python-inline-code", "pip-install-break-system-packages"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Python conceptual corpus")
	}
}

func TestJavaScriptSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "javascript.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled JavaScript pack = %#v", bundledPack)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"bun-install-instal", "bun-run-rnu", "deno-run-rn", "deno-test-tes", "npx-create-creat"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched JavaScript corpus")
	}
}

func TestJavaScriptFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "javascript.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	if risk["node-version-verison"] != diagnose.RiskSafe || risk["bun-version-verison"] != diagnose.RiskSafe || risk["deno-version-verison"] != diagnose.RiskSafe || risk["node-no-experimental-require-module"] != diagnose.RiskUnknown {
		t.Fatalf("JavaScript flag risks = %#v", risk)
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched JavaScript flag corpus")
	}
}

func TestJavaScriptPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "javascript.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"node-entrypoint-inde", "bun-run-entrypoint-inde", "deno-run-entrypoint-tss", "deno-task-config-josn"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched JavaScript path corpus")
	}
}

func TestJavaScriptConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "javascript.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"node-eval", "deno-run-allow-all", "npx-yes"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched JavaScript conceptual corpus")
	}
}

func TestPackageManagerSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "package-managers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	if err != nil {
		t.Fatal(err)
	}
	var bundledPack Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledPack = candidate
		}
	}
	if bundledPack.Version != pack.Version || !slices.Equal(bundledPack.Rules, pack.Rules) {
		t.Fatalf("bundled package manager pack = %#v", bundledPack)
	}
	for _, rule := range pack.Rules {
		if rule.Risk != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", rule.ID, rule.Risk)
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched package manager corpus")
	}
}

func TestPackageManagerFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "package-managers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	for _, rule := range pack.Rules {
		if rule.Risk != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", rule.ID, rule.Risk)
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched package manager flag corpus")
	}
}

func TestPackageManagerPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "package-managers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	for _, rule := range pack.Rules {
		if rule.Risk != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", rule.ID, rule.Risk)
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched package manager path corpus")
	}
}

func TestPackageManagerConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "package-managers.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"npm-publish", "npm-audit-fix-force", "pnpm-update-latest", "brew-upgrade"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched package manager conceptual corpus")
	}
}

func TestGitSubcommandTypoRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "core-git.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "git-subcommand-typos"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	bundled, err := LoadBundled()
	var bundledGit Pack
	for _, candidate := range bundled {
		if candidate.ID == pack.ID {
			bundledGit = candidate
		}
	}
	if err != nil || bundledGit.Version != pack.Version || !slices.Equal(bundledGit.Rules, pack.Rules) {
		t.Fatalf("bundled Git pack = %#v, %v", bundled, err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"git-checkout-chekcout", "git-commit-comit", "git-push-puhs"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Git subcommand corpus")
	}
}

func TestGitFlagRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "core-git.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "git-flag-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"git-rebase-preserve-merges", "git-pull-rebase-preserve"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Git flag corpus")
	}
}

func TestGitPathRepairRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "core-git.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "git-path-repairs"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	risk := map[string]diagnose.Risk{}
	for _, rule := range pack.Rules {
		risk[rule.ID] = rule.Risk
	}
	for _, id := range []string{"git-add-gitingore", "git-add-readme-mkd", "git-add-github-workflow"} {
		if risk[id] != diagnose.RiskHigh {
			t.Fatalf("risk for %s = %q, want high", id, risk[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched Git path corpus")
	}
}

func TestGitConceptualMisuseRules(t *testing.T) {
	pack, err := Load(filepath.Join("..", "..", "packs", "core-git.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "git-conceptual-misuse"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	rules := map[string]Rule{}
	for _, rule := range pack.Rules {
		rules[rule.ID] = rule
	}
	for _, id := range []string{"git-push-force", "git-reset-hard", "git-clean-force"} {
		if rules[id].Risk != diagnose.RiskHigh || rules[id].Cause == "" {
			t.Fatalf("conceptual rule %s = %#v", id, rules[id])
		}
	}
	corpus[0].Cases[0].RuleID = "missing"
	if err := RunFixtureCorpus(pack, corpus); err == nil {
		t.Fatal("accepted mismatched conceptual Git corpus")
	}
}

func TestSignedGitPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "git-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "git-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "git-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "git-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed pack fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed pack fixture")
	}
}

func TestSignedPackageManagerPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "package-manager-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "package-manager-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "package-manager-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "package-manager-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed package manager fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed package manager fixture")
	}
}

func TestSignedJavaScriptPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "javascript-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "javascript-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "javascript-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "javascript-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed JavaScript fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed JavaScript fixture")
	}
}

func TestSignedPythonPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "python-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "python-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "python-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "python-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed Python fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed Python fixture")
	}
}

func TestSignedRustPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "rust-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "rust-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "rust-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "rust-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed Rust fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed Rust fixture")
	}
}

func TestSignedGoPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "go-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "go-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "go-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "go-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed Go fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed Go fixture")
	}
}

func TestSignedContainersPackFixtureAndRegressionCorpus(t *testing.T) {
	directory := filepath.Join("..", "..", "packs", "fixtures", "signed")
	keyring, err := LoadKeyring(filepath.Join(directory, "keyring.json"))
	if err != nil {
		t.Fatal(err)
	}
	payload, err := os.ReadFile(filepath.Join(directory, "containers-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	signature, err := base64.RawStdEncoding.DecodeString(strings.TrimSpace(string(mustReadFile(t, filepath.Join(directory, "containers-regression.sig")))))
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	pack, err := Load(filepath.Join(directory, "containers-regression.json"))
	if err != nil {
		t.Fatal(err)
	}
	corpus, err := LoadFixtureCorpus(filepath.Join("..", "..", "packs", "corpus", "containers-signed-regression"))
	if err != nil {
		t.Fatal(err)
	}
	if err := RunFixtureCorpus(pack, corpus); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(append(payload, ' '), signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted tampered signed container fixture")
	}
	if !keyring.Revoke("close-enough") {
		t.Fatal("did not revoke fixture publisher")
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked signed container fixture")
	}
}

func mustReadFile(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestExtractGitFailureEvidence(t *testing.T) {
	output := "fatal: pathspec '.gitingore' did not match any file(s) known to git\nerror: unknown option '--shortt'\ngit: 'statsu' is not a git command. See 'git --help'.\nerror: unknown option '--shortt'\n"
	evidence, err := ExtractGitFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "git-pathspec-miss", Value: ".gitingore"},
		{Kind: "git-unknown-option", Value: "--shortt"},
		{Kind: "git-unknown-subcommand", Value: "statsu"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractGitFailureEvidence("git: 'statsu' is not a git command.\nerror: unknown option '--shortt'\nfatal: pathspec '.gitingore' did not match any file(s) known to git\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractGitFailureEvidence("git: 'https://user:password@example.invalid/repo' is not a git command\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/repo" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if _, err := ExtractGitFailureEvidence(strings.Repeat("x", maxGitFailureOutputBytes+1)); !errors.Is(err, ErrGitFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractPackageManagerFailureEvidence(t *testing.T) {
	output := "error Command \"buid\" not found.\nnpm error code E404\nERR_PNPM_NO_MATCHING_VERSION\nError: No available formula with the name \"fooo\".\nnpm error Missing script: \"buid\"\nnpm error code E404\n"
	evidence, err := ExtractPackageManagerFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "brew-missing-formula", Value: "fooo"},
		{Kind: "npm-error-code", Value: "E404"},
		{Kind: "npm-missing-script", Value: "buid"},
		{Kind: "pnpm-error-code", Value: "ERR_PNPM_NO_MATCHING_VERSION"},
		{Kind: "yarn-unknown-command", Value: "buid"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractPackageManagerFailureEvidence("npm error Missing script: \"buid\"\nError: No available formula with the name \"fooo\".\nERR_PNPM_NO_MATCHING_VERSION\nnpm error code E404\nerror Command \"buid\" not found.\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractPackageManagerFailureEvidence("error Command \"https://user:password@example.invalid\" not found.\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if _, err := ExtractPackageManagerFailureEvidence(strings.Repeat("x", maxPackageManagerFailureOutputBytes+1)); !errors.Is(err, ErrPackageManagerFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractJavaScriptFailureEvidence(t *testing.T) {
	output := "Error [ERR_MODULE_NOT_FOUND]: Cannot find module './src/inde.js'\nerror: Module not found \"./main.tss\"\nerror: Could not resolve: \"left-pad\"\nnode: bad option: --verison\nnode: bad option: --verison\n"
	evidence, err := ExtractJavaScriptFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "bun-unresolved-module", Value: "left-pad"},
		{Kind: "deno-module-not-found", Value: "./main.tss"},
		{Kind: "node-module-not-found", Value: "./src/inde.js"},
		{Kind: "node-unknown-option", Value: "--verison"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractJavaScriptFailureEvidence("node: bad option: --verison\nerror: Could not resolve: \"left-pad\"\nerror: Module not found \"./main.tss\"\nError [ERR_MODULE_NOT_FOUND]: Cannot find module './src/inde.js'\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractJavaScriptFailureEvidence("Error: Cannot find module 'https://user:password@example.invalid/app.js'\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/app.js" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if _, err := ExtractJavaScriptFailureEvidence(strings.Repeat("x", maxJavaScriptFailureOutputBytes+1)); !errors.Is(err, ErrJavaScriptFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractPythonFailureEvidence(t *testing.T) {
	output := "ModuleNotFoundError: No module named 'requsets'\nFileNotFoundError: [Errno 2] No such file or directory: './src/maine.py'\nERROR: Could not find a version that satisfies the requirement requsets\npytest: error: unrecognized arguments: --collect-onyl\n"
	evidence, err := ExtractPythonFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{{Kind: "pip-package-not-found", Value: "requsets"}, {Kind: "pytest-unknown-argument", Value: "--collect-onyl"}, {Kind: "python-module-not-found", Value: "requsets"}, {Kind: "python-path-not-found", Value: "./src/maine.py"}}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	redacted, err := ExtractPythonFailureEvidence("ModuleNotFoundError: No module named 'https://user:password@example.invalid/mod'\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/mod" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if _, err := ExtractPythonFailureEvidence(strings.Repeat("x", maxPythonFailureOutputBytes+1)); !errors.Is(err, ErrPythonFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractRustFailureEvidence(t *testing.T) {
	output := "error: no such command: `buid`\nerror: unexpected argument '--relese' found\nerror: the manifest-path must be a path to a Cargo.toml file: `/tmp/Cargo.tmol`\nerror: couldn't read `./src/mian.rs`: No such file or directory (os error 2)\nerror: invalid value 'updat' for '[+toolchain]': error: \"updat\" is not a valid subcommand\nerror: no such command: `buid`\n"
	evidence, err := ExtractRustFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "cargo-manifest-path-invalid", Value: "/tmp/Cargo.tmol"},
		{Kind: "cargo-unknown-argument", Value: "--relese"},
		{Kind: "cargo-unknown-subcommand", Value: "buid"},
		{Kind: "rustc-source-not-found", Value: "./src/mian.rs"},
		{Kind: "rustup-invalid-toolchain", Value: "updat"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractRustFailureEvidence("error: invalid value 'updat' for '[+toolchain]': error: \"updat\" is not a valid subcommand\nerror: couldn't read `./src/mian.rs`: No such file or directory (os error 2)\nerror: the manifest-path must be a path to a Cargo.toml file: `/tmp/Cargo.tmol`\nerror: unexpected argument '--relese' found\nerror: no such command: `buid`\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractRustFailureEvidence("error: couldn't read `https://user:password@example.invalid/main.rs`: No such file or directory (os error 2)\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/main.rs" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if evidence, err := ExtractRustFailureEvidence("error: unrelated"); err != nil || len(evidence) != 0 {
		t.Fatalf("unmatched evidence = %#v, %v", evidence, err)
	}
	if _, err := ExtractRustFailureEvidence(strings.Repeat("x", maxRustFailureOutputBytes+1)); !errors.Is(err, ErrRustFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractGoFailureEvidence(t *testing.T) {
	output := "go buid: unknown command\nflag provided but not defined: -counnt\ngo: open go.mdo: no such file or directory\nlstat ./cmd/mian.go: no such file or directory\ngo buid: unknown command\n"
	evidence, err := ExtractGoFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "go-flag-unknown", Value: "-counnt"},
		{Kind: "go-modfile-missing", Value: "go.mdo"},
		{Kind: "go-path-missing", Value: "./cmd/mian.go"},
		{Kind: "go-unknown-subcommand", Value: "buid"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractGoFailureEvidence("go buid: unknown command\nlstat ./cmd/mian.go: no such file or directory\ngo: open go.mdo: no such file or directory\nflag provided but not defined: -counnt\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractGoFailureEvidence("lstat https://user:password@example.invalid/main.go: no such file or directory\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/main.go" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if evidence, err := ExtractGoFailureEvidence("go: unrelated"); err != nil || len(evidence) != 0 {
		t.Fatalf("unmatched evidence = %#v, %v", evidence, err)
	}
	if _, err := ExtractGoFailureEvidence(strings.Repeat("x", maxGoFailureOutputBytes+1)); !errors.Is(err, ErrGoFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestExtractContainerFailureEvidence(t *testing.T) {
	output := "docker: unknown command: docker bulid\nunknown flag: --detachd\nERROR: failed to build: failed to read dockerfile: open Dockerfil: no such file or directory\nopen compose.yamll: no such file or directory\ndocker: unknown command: docker bulid\n"
	evidence, err := ExtractContainerFailureEvidence(output)
	if err != nil {
		t.Fatal(err)
	}
	want := []diagnose.Evidence{
		{Kind: "container-file-not-found", Value: "Dockerfil"},
		{Kind: "container-file-not-found", Value: "compose.yamll"},
		{Kind: "container-unknown-command", Value: "bulid"},
		{Kind: "container-unknown-flag", Value: "--detachd"},
	}
	if !slices.Equal(evidence, want) {
		t.Fatalf("evidence = %#v, want %#v", evidence, want)
	}
	reversed, err := ExtractContainerFailureEvidence("unknown flag: --detachd\nopen compose.yamll: no such file or directory\nERROR: failed to build: failed to read dockerfile: open Dockerfil: no such file or directory\ndocker: unknown command: docker bulid\n")
	if err != nil || !slices.Equal(reversed, want) {
		t.Fatalf("reversed evidence = %#v, %v", reversed, err)
	}
	redacted, err := ExtractContainerFailureEvidence("error: open https://user:password@example.invalid/compose.yaml: no such file or directory\n")
	if err != nil || len(redacted) != 1 || redacted[0].Value != "https://[REDACTED]@example.invalid/compose.yaml" {
		t.Fatalf("redacted evidence = %#v, %v", redacted, err)
	}
	if evidence, err := ExtractContainerFailureEvidence("container: unrelated"); err != nil || len(evidence) != 0 {
		t.Fatalf("unmatched evidence = %#v, %v", evidence, err)
	}
	if _, err := ExtractContainerFailureEvidence(strings.Repeat("x", maxContainerFailureOutputBytes+1)); !errors.Is(err, ErrContainerFailureOutputTooLarge) {
		t.Fatalf("oversized failure output = %v", err)
	}
}

func TestResolveOrdersPacksAndRejectsConflicts(t *testing.T) {
	pack := func(id, ruleID, pattern string) Pack {
		return Pack{SchemaVersion: SchemaVersionV1, ID: id, Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: ruleID, Command: "git", Pattern: pattern, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	}
	resolved, err := Resolve([]Pack{pack("zeta", "zeta-rule", "zeta"), pack("alpha", "alpha-rule", "alpha")})
	if err != nil || len(resolved) != 2 || resolved[0].Pack.ID != "alpha" || resolved[1].Pack.ID != "zeta" {
		t.Fatalf("resolved packs = %#v, %v", resolved, err)
	}
	for _, packs := range [][]Pack{
		{pack("alpha", "one", "one"), pack("alpha", "two", "two")},
		{pack("alpha", "one", "same"), pack("beta", "two", "same")},
	} {
		if _, err := Resolve(packs); err == nil {
			t.Fatalf("accepted conflicting packs %#v", packs)
		}
	}
}

func TestPackCompatibilityRequirements(t *testing.T) {
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", MinEngineVersion: "1.0.0", Capabilities: []string{"matcher-v1", "risk-v1"}, Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	if err := pack.CheckCompatibility("1.0.0"); err != nil {
		t.Fatal(err)
	}
	if err := pack.CheckCompatibility("0.9.0"); err == nil {
		t.Fatal("accepted old engine")
	}
	pack.Capabilities = []string{"unknown-v1"}
	if err := pack.CheckCompatibility(EngineVersion); err == nil {
		t.Fatal("accepted unsupported capability")
	}
	pack.Capabilities = []string{"matcher-v1", "matcher-v1"}
	if err := pack.Validate(); err == nil {
		t.Fatal("accepted duplicate capabilities")
	}
	for _, test := range []struct {
		left, right string
		want        int
	}{
		{"1.0.0-alpha.2", "1.0.0-alpha.10", -1},
		{"1.0.0", "1.0.0-rc.1", 1},
		{"1.0.0+build.1", "1.0.0+build.2", 0},
	} {
		if got := compareVersion(test.left, test.right); got != test.want {
			t.Fatalf("compareVersion(%q, %q) = %d, want %d", test.left, test.right, got, test.want)
		}
	}
}

func TestLoadBundledPacksIsDeterministicAndReadOnly(t *testing.T) {
	names, err := BundledNames()
	if err != nil || !slices.Equal(names, []string{"core-containers.json", "core-git.json", "core-go.json", "core-javascript.json", "core-package-managers.json", "core-python.json", "core-rust.json"}) {
		t.Fatalf("bundled names = %#v, %v", names, err)
	}
	packs, err := LoadBundled()
	if err != nil || len(packs) != 7 || packs[0].ID != "core-containers" || packs[1].ID != "core-git" || packs[2].ID != "core-go" || packs[3].ID != "core-javascript" || packs[4].ID != "core-package-managers" || packs[5].ID != "core-python" || packs[6].ID != "core-rust" {
		t.Fatalf("bundled packs = %#v, %v", packs, err)
	}
	packs[0].Rules[0].ID = "mutated"
	reloaded, err := LoadBundled()
	if err != nil || reloaded[0].Rules[0].ID != "docker-build-bulid" {
		t.Fatalf("bundled pack mutation leaked: %#v, %v", reloaded, err)
	}
}

func TestInstallPackAtomicallyWithoutOverwrite(t *testing.T) {
	directory := t.TempDir()
	source := filepath.Join(directory, "source.json")
	data := []byte(`{"schema_version":1,"id":"core-git","version":"1.0.0","publisher":"close-enough","rules":[{"id":"git-status","command":"git","pattern":"status","replacement":"status","cause":"typo","risk":"safe","risk_rationale":"read-only status query"}]}`)
	if err := os.WriteFile(source, data, 0o600); err != nil {
		t.Fatal(err)
	}
	targetDirectory := filepath.Join(directory, "installed")
	target, err := Install(source, targetDirectory)
	if err != nil {
		t.Fatal(err)
	}
	installed, err := os.ReadFile(target)
	if err != nil || string(installed) != string(data) {
		t.Fatalf("installed pack = %q, %v", installed, err)
	}
	if _, err := Install(source, targetDirectory); err == nil {
		t.Fatal("expected no-overwrite failure")
	}
}

func TestUninstallPackOnlyRemovesManagedRegularFile(t *testing.T) {
	directory := t.TempDir()
	target := filepath.Join(directory, "core-git-1.0.0.json")
	if err := os.WriteFile(target, []byte("pack"), 0o600); err != nil {
		t.Fatal(err)
	}
	removed, err := Uninstall(directory, "core-git", "1.0.0")
	if err != nil || removed != target {
		t.Fatalf("uninstall = %q, %v", removed, err)
	}
	if _, err := os.Lstat(target); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("pack remains after uninstall: %v", err)
	}
	if _, err := Uninstall(directory, "core-git", "1.0.0"); err == nil {
		t.Fatal("expected missing pack error")
	}
	if _, err := Uninstall(directory, "../core", "1.0.0"); err == nil {
		t.Fatal("expected invalid target error")
	}
}

func TestPackEnableDisableStateStore(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	state, err := LoadState(path)
	if err != nil || !state.Enable("core-git") || state.Enable("core-git") || !state.Enable("containers") {
		t.Fatalf("enable state = %#v, %v", state, err)
	}
	if err := WriteState(path, state); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadState(path)
	if err != nil || !loaded.EnabledFor("core-git") || !loaded.Disable("core-git") || loaded.Disable("core-git") {
		t.Fatalf("loaded state = %#v, %v", loaded, err)
	}
	if err := WriteState(path, loaded); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadState(path); err != nil {
		t.Fatal(err)
	}
}

func TestPackStateRejectsInvalidOrUnknownData(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	for _, data := range [][]byte{
		[]byte(`{"enabled":["core-git","core-git"]}`),
		[]byte(`{"enabled":["Core"]}`),
		[]byte(`{"enabled":[],"unknown":true}`),
	} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadState(path); err == nil {
			t.Fatalf("accepted invalid state %s", data)
		}
	}
}

func TestVerifyDetachedPackSignature(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte(`{"id":"core-git"}`)
	signature := ed25519.Sign(privateKey, payload)
	if err := VerifyDetachedSignature(payload, signature, publicKey); err != nil {
		t.Fatal(err)
	}
	if err := VerifyDetachedSignature([]byte(`{"id":"other"}`), signature, publicKey); err == nil {
		t.Fatal("accepted tampered payload")
	}
	if err := VerifyDetachedSignature(payload, signature[:len(signature)-1], publicKey); err == nil {
		t.Fatal("accepted malformed signature")
	}
	path := filepath.Join(t.TempDir(), "pack.json")
	signaturePath := path + ".sig"
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(signaturePath, signature, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyDetachedFiles(path, signaturePath, publicKey); err != nil {
		t.Fatal(err)
	}
}

func TestPublisherKeyringLifecycle(t *testing.T) {
	publicKey, _, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var keyring Keyring
	if err := keyring.Add("close-enough", publicKey); err != nil {
		t.Fatal(err)
	}
	if err := keyring.Add("close-enough", publicKey); err == nil {
		t.Fatal("accepted duplicate publisher")
	}
	path := filepath.Join(t.TempDir(), "keyring.json")
	if err := WriteKeyring(path, keyring); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadKeyring(path)
	if err != nil {
		t.Fatal(err)
	}
	key, ok := loaded.PublicKey("close-enough")
	if !ok || !bytes.Equal(key, publicKey) || !loaded.Remove("close-enough") || loaded.Remove("close-enough") {
		t.Fatalf("keyring state = %#v", loaded)
	}
}

func TestKeyringRejectsMalformedKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "keyring.json")
	for _, data := range [][]byte{
		[]byte(`{"publishers":[{"id":"close-enough","public_key":"not-base64"}]}`),
		[]byte(`{"publishers":[{"id":"Close","public_key":""}]}`),
		[]byte(`{"publishers":[],"unknown":true}`),
	} {
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := LoadKeyring(path); err == nil {
			t.Fatalf("accepted invalid keyring %s", data)
		}
	}
}

func TestRevokedPublisherKeyCannotVerify(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte("pack")
	signature := ed25519.Sign(privateKey, payload)
	var keyring Keyring
	if err := keyring.Add("close-enough", publicKey); err != nil {
		t.Fatal(err)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err != nil {
		t.Fatal(err)
	}
	if !keyring.Revoke("close-enough") || keyring.Revoke("close-enough") || !keyring.RevokedFor("close-enough") {
		t.Fatalf("revocations = %#v", keyring.Revoked)
	}
	if err := VerifyPublisherSignature(payload, signature, "close-enough", keyring); err == nil {
		t.Fatal("accepted revoked publisher")
	}
}

func TestVerifyTUFRootBootstrap(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var key TUFKey
	key.KeyType, key.Scheme = "ed25519", "ed25519"
	key.KeyVal.Public = base64.RawStdEncoding.EncodeToString(publicKey)
	root := TUFRoot{Type: "root", Version: 1, Keys: map[string]TUFKey{"root-key": key}, Roles: map[string]TUFRole{"root": {KeyIDs: []string{"root-key"}, Threshold: 1}}}
	payload, err := CanonicalRootPayload(root)
	if err != nil {
		t.Fatal(err)
	}
	envelope := TUFEnvelope{Signed: payload, Signatures: []TUFSignature{{KeyID: "root-key", Sig: hex.EncodeToString(ed25519.Sign(privateKey, payload))}}}
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	verified, err := VerifyRootBootstrap(data, map[string]ed25519.PublicKey{"root-key": publicKey})
	if err != nil || verified.Version != 1 {
		t.Fatalf("verified root = %#v, %v", verified, err)
	}
	if _, err := VerifyRootBootstrap(data, map[string]ed25519.PublicKey{}); err == nil {
		t.Fatal("accepted missing trust anchor")
	}
	envelope.Signatures[0].Sig = hex.EncodeToString(ed25519.Sign(privateKey, []byte("tampered")))
	data, err = json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyRootBootstrap(data, map[string]ed25519.PublicKey{"root-key": publicKey}); err == nil {
		t.Fatal("accepted tampered root signature")
	}
}

func TestVerifyTUFTimestamp(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var key TUFKey
	key.KeyType, key.Scheme = "ed25519", "ed25519"
	key.KeyVal.Public = base64.RawStdEncoding.EncodeToString(publicKey)
	root := TUFRoot{Type: "root", Version: 1, Keys: map[string]TUFKey{"timestamp-key": key}, Roles: map[string]TUFRole{"root": {KeyIDs: []string{"timestamp-key"}, Threshold: 1}, "timestamp": {KeyIDs: []string{"timestamp-key"}, Threshold: 1}}}
	timestamp := TUFTimestamp{Type: "timestamp", Version: 1, Expires: "2030-01-01T00:00:00Z", Meta: map[string]TUFMetaFile{"snapshot.json": {Version: 1}}}
	payload, err := json.Marshal(timestamp)
	if err != nil {
		t.Fatal(err)
	}
	envelope := TUFEnvelope{Signed: payload, Signatures: []TUFSignature{{KeyID: "timestamp-key", Sig: hex.EncodeToString(ed25519.Sign(privateKey, payload))}}}
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	verified, err := VerifyTimestamp(data, root)
	if err != nil || verified.Meta["snapshot.json"].Version != 1 {
		t.Fatalf("timestamp = %#v, %v", verified, err)
	}
	envelope.Signatures[0].Sig = hex.EncodeToString(ed25519.Sign(privateKey, []byte("tampered")))
	data, err = json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyTimestamp(data, root); err == nil {
		t.Fatal("accepted invalid timestamp signature")
	}
}

func TestVerifyTUFSnapshot(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var key TUFKey
	key.KeyType, key.Scheme = "ed25519", "ed25519"
	key.KeyVal.Public = base64.RawStdEncoding.EncodeToString(publicKey)
	root := TUFRoot{Type: "root", Version: 1, Keys: map[string]TUFKey{"snapshot-key": key}, Roles: map[string]TUFRole{"root": {KeyIDs: []string{"snapshot-key"}, Threshold: 1}, "snapshot": {KeyIDs: []string{"snapshot-key"}, Threshold: 1}}}
	timestamp := TUFTimestamp{Type: "timestamp", Version: 1, Expires: "2030-01-01T00:00:00Z", Meta: map[string]TUFMetaFile{"snapshot.json": {Version: 2}}}
	snapshot := TUFSnapshot{Type: "snapshot", Version: 2, Expires: "2030-01-01T00:00:00Z", Meta: map[string]TUFMetaFile{"targets.json": {Version: 1}}}
	payload, err := json.Marshal(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	envelope := TUFEnvelope{Signed: payload, Signatures: []TUFSignature{{KeyID: "snapshot-key", Sig: hex.EncodeToString(ed25519.Sign(privateKey, payload))}}}
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifySnapshot(data, root, timestamp); err != nil {
		t.Fatal(err)
	}
	timestamp.Meta["snapshot.json"] = TUFMetaFile{Version: 3}
	if _, err := VerifySnapshot(data, root, timestamp); err == nil {
		t.Fatal("accepted snapshot version mismatch")
	}
}

func TestVerifyTUFTargets(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	var key TUFKey
	key.KeyType, key.Scheme = "ed25519", "ed25519"
	key.KeyVal.Public = base64.RawStdEncoding.EncodeToString(publicKey)
	root := TUFRoot{Type: "root", Version: 1, Keys: map[string]TUFKey{"targets-key": key}, Roles: map[string]TUFRole{"root": {KeyIDs: []string{"targets-key"}, Threshold: 1}, "targets": {KeyIDs: []string{"targets-key"}, Threshold: 1}}}
	snapshot := TUFSnapshot{Type: "snapshot", Version: 1, Expires: "2030-01-01T00:00:00Z", Meta: map[string]TUFMetaFile{"targets.json": {Version: 1}}}
	targets := TUFTargets{Type: "targets", Version: 1, Expires: "2030-01-01T00:00:00Z", Targets: map[string]TUFMetaFile{"core-git.json": {Length: 1, Hashes: map[string]string{"sha256": "00"}}}}
	payload, err := json.Marshal(targets)
	if err != nil {
		t.Fatal(err)
	}
	envelope := TUFEnvelope{Signed: payload, Signatures: []TUFSignature{{KeyID: "targets-key", Sig: hex.EncodeToString(ed25519.Sign(privateKey, payload))}}}
	data, err := json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyTargets(data, root, snapshot); err != nil {
		t.Fatal(err)
	}
	targets.Targets = map[string]TUFMetaFile{"../pack.json": {Length: 1, Hashes: map[string]string{"sha256": "00"}}}
	payload, err = json.Marshal(targets)
	if err != nil {
		t.Fatal(err)
	}
	envelope.Signed = payload
	envelope.Signatures[0].Sig = hex.EncodeToString(ed25519.Sign(privateKey, payload))
	data, err = json.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyTargets(data, root, snapshot); err == nil {
		t.Fatal("accepted unsafe target path")
	}
}

func TestRegistryMetadataRejectsExpiryAndRollback(t *testing.T) {
	now := time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	var state RegistryState
	if err := state.Accept("timestamp", 2, "2030-01-02T00:00:00Z", now); err != nil {
		t.Fatal(err)
	}
	if err := state.Accept("timestamp", 1, "2030-01-02T00:00:00Z", now); err == nil {
		t.Fatal("accepted metadata rollback")
	}
	if err := state.Accept("snapshot", 1, "2030-01-01T00:00:00Z", now); err == nil {
		t.Fatal("accepted expired metadata")
	}
	if err := state.Accept("targets", 1, "invalid", now); err == nil {
		t.Fatal("accepted invalid expiry")
	}
}

func TestRegistryOptInStateMachine(t *testing.T) {
	state := RegistryDisabled
	for _, event := range []RegistryOptInEvent{RegistryRequest, RegistryConfirm} {
		var err error
		state, err = TransitionRegistryOptIn(state, event)
		if err != nil {
			t.Fatal(err)
		}
	}
	if !state.Allowed() {
		t.Fatal("registry enabled without permission")
	}
	state, err := TransitionRegistryOptIn(state, RegistryRevoke)
	if err != nil || state != RegistryDisabled || state.Allowed() {
		t.Fatalf("registry revoke = %s, %v", state, err)
	}
	if _, err := TransitionRegistryOptIn(RegistryDisabled, RegistryConfirm); err == nil {
		t.Fatal("accepted confirmation without request")
	}
}

func TestAutoUpdateOptInRequiresRegistryOptIn(t *testing.T) {
	state, err := TransitionAutoUpdateOptIn(AutoUpdateDisabled, AutoUpdateRequest, RegistryDisabled)
	if err != nil || state != AutoUpdatePending {
		t.Fatalf("auto-update request = %s, %v", state, err)
	}
	if _, err := TransitionAutoUpdateOptIn(state, AutoUpdateConfirm, RegistryDisabled); err == nil {
		t.Fatal("enabled auto-update without registry opt-in")
	}
	state, err = TransitionAutoUpdateOptIn(state, AutoUpdateConfirm, RegistryEnabled)
	if err != nil || !state.Allowed() {
		t.Fatalf("auto-update confirmation = %s, %v", state, err)
	}
	state, err = TransitionAutoUpdateOptIn(state, AutoUpdateRevoke, RegistryEnabled)
	if err != nil || state != AutoUpdateDisabled {
		t.Fatalf("auto-update revoke = %s, %v", state, err)
	}
}

type failingReader struct{ reads int }

func (r *failingReader) Read(buffer []byte) (int, error) {
	if r.reads > 0 {
		return 0, errors.New("download failed")
	}
	r.reads++
	copy(buffer, "partial")
	return len("partial"), nil
}

func TestTransactionalPackDownloadStaging(t *testing.T) {
	directory := t.TempDir()
	staged, err := StageDownload(directory, strings.NewReader("pack"))
	if err != nil || staged.Size != 4 {
		t.Fatalf("staged download = %#v, %v", staged, err)
	}
	if _, err := os.Stat(staged.Path()); err != nil {
		t.Fatal(err)
	}
	if err := staged.Discard(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(staged.Path()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("staging file remains: %v", err)
	}
	if _, err := StageDownload(directory, &failingReader{}); err == nil {
		t.Fatal("accepted failed download")
	}
	entries, err := os.ReadDir(directory)
	if err != nil || len(entries) != 0 {
		t.Fatalf("staging residue = %#v, %v", entries, err)
	}
}

func TestAtomicVerifiedPackActivation(t *testing.T) {
	directory := t.TempDir()
	data := `{"schema_version":1,"id":"core-git","version":"1.0.0","publisher":"close-enough","rules":[{"id":"git-status","command":"git","pattern":"status","replacement":"status","cause":"typo","risk":"safe","risk_rationale":"read-only status query"}]}`
	staged, err := StageDownload(directory, strings.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	target, err := ActivateStagedPack(staged, directory)
	if err != nil || filepath.Base(target) != "core-git-1.0.0.json" {
		t.Fatalf("activation = %q, %v", target, err)
	}
	invalid, err := StageDownload(directory, strings.NewReader("invalid"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ActivateStagedPack(invalid, directory); err == nil {
		t.Fatal("activated invalid pack")
	}
	if _, err := os.Stat(invalid.Path()); err != nil {
		t.Fatalf("invalid stage unexpectedly removed: %v", err)
	}
	if err := invalid.Discard(); err != nil {
		t.Fatal(err)
	}
}

func TestPackUpdateRollsBackOnActivationFailure(t *testing.T) {
	directory := t.TempDir()
	previous := `{"schema_version":1,"id":"core-git","version":"1.0.0","publisher":"close-enough","rules":[{"id":"git-status","command":"git","pattern":"status","replacement":"status","cause":"old","risk":"safe","risk_rationale":"read-only status query"}]}`
	updated := `{"schema_version":1,"id":"core-git","version":"1.0.0","publisher":"close-enough","rules":[{"id":"git-status","command":"git","pattern":"status","replacement":"status","cause":"new","risk":"safe","risk_rationale":"read-only status query"}]}`
	target := filepath.Join(directory, "core-git-1.0.0.json")
	if err := os.WriteFile(target, []byte(previous), 0o600); err != nil {
		t.Fatal(err)
	}
	staged, err := StageDownload(directory, strings.NewReader(updated))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := activateStagedPack(staged, directory, func(string, []byte) error { return errors.New("activation failed") }); err == nil {
		t.Fatal("accepted failed activation")
	}
	data, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != previous {
		t.Fatalf("rollback = %q, want %q", data, previous)
	}
}

func TestRegistryRefreshUsesConfirmedRegistry(t *testing.T) {
	pack := func(cause string) Pack {
		return Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: cause, Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	}
	called := false
	result, err := RefreshRegistry(RegistryEnabled, []Pack{pack("cached")}, func() ([]Pack, error) {
		called = true
		return []Pack{pack("updated")}, nil
	})
	if err != nil || !called || !result.Updated || result.Offline {
		t.Fatalf("refresh = %#v, %v, called=%t", result, err, called)
	}
	if len(result.Packs) != 1 || result.Packs[0].Rules[0].Cause != "updated" {
		t.Fatalf("updated packs = %#v", result.Packs)
	}
	called = false
	result, err = RefreshRegistry(RegistryPending, []Pack{pack("cached")}, func() ([]Pack, error) {
		called = true
		return nil, nil
	})
	if err != nil || called || result.Updated || result.Offline || result.Packs[0].Rules[0].Cause != "cached" {
		t.Fatalf("unconfirmed refresh = %#v, %v, called=%t", result, err, called)
	}
}

func TestRegistryRefreshOfflinePreservesCachedPacks(t *testing.T) {
	cached := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: "cached", Risk: diagnose.RiskSafe, RiskRationale: "read-only status query"}}}
	result, err := RefreshRegistry(RegistryEnabled, []Pack{cached}, func() ([]Pack, error) {
		return nil, errors.New("network unavailable")
	})
	if !errors.Is(err, ErrRegistryOffline) || !result.Offline || result.Updated {
		t.Fatalf("offline refresh = %#v, %v", result, err)
	}
	if len(result.Packs) != 1 || result.Packs[0].Rules[0].Cause != "cached" {
		t.Fatalf("cached packs = %#v", result.Packs)
	}
}
