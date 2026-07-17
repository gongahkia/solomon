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

func TestRejectInvalidPattern(t *testing.T) {
	pack := Pack{SchemaVersion: 1, ID: "core", Version: "1", Publisher: "close-enough", Rules: []Rule{{ID: "bad", Command: "git", Pattern: "[", Replacement: "status", Cause: "typo", Risk: diagnose.RiskSafe}}}
	if err := pack.Validate(); err == nil {
		t.Fatal("expected error")
	}
}
