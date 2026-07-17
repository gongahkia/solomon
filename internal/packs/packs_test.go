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
	if err != nil || !slices.Equal(names, []string{"core-git.json"}) {
		t.Fatalf("bundled names = %#v, %v", names, err)
	}
	packs, err := LoadBundled()
	if err != nil || len(packs) != 1 || packs[0].ID != "core-git" {
		t.Fatalf("bundled packs = %#v, %v", packs, err)
	}
	packs[0].Rules[0].ID = "mutated"
	reloaded, err := LoadBundled()
	if err != nil || reloaded[0].Rules[0].ID != "git-status-typo" {
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
