package packs

import (
	"os"
	"testing"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

func TestValidatePack(t *testing.T) {
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "^sttaus$", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
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
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "bad", Command: "git", Pattern: "[", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
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
	base := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: "status", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
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
	pack := Pack{SchemaVersion: SchemaVersionV1, ID: "core-git", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "git-status", Command: "git", Pattern: `^sttaus$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
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
	injection := Pack{SchemaVersion: SchemaVersionV1, ID: "literal", Version: "1.0.0", Publisher: "close-enough", Rules: []Rule{{ID: "literal-text", Command: "git", Pattern: `^\$\(touch .+\)$`, Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
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
