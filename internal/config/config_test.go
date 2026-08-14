package config

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/credential"
	"github.com/gongahkia/close-enough/internal/history"
)

type trustedProjectFixture struct {
	Name          string `json:"name"`
	Config        string `json:"config"`
	ConfigMode    string `json:"config_mode"`
	Marker        string `json:"marker"`
	MarkerMode    string `json:"marker_mode"`
	DirectoryMode string `json:"directory_mode"`
	Trusted       bool   `json:"trusted"`
	Mode          string `json:"mode"`
}

func TestSetValidatesMode(t *testing.T) {
	cfg := Default()
	if err := cfg.Set("mode", "interrupt"); err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "interrupt" {
		t.Fatal(cfg.Mode)
	}
	if err := cfg.Set("mode", "unsafe"); err == nil {
		t.Fatal("expected error")
	}
}

func TestSetConfiguresDisplayFields(t *testing.T) {
	cfg := Default()
	if err := cfg.Set("display.cause", "false"); err != nil || cfg.Display.Cause {
		t.Fatalf("display cause = %#v, %v", cfg.Display, err)
	}
	if err := cfg.Set("display.trace", "true"); err != nil || !cfg.Display.Trace {
		t.Fatalf("display trace = %#v, %v", cfg.Display, err)
	}
	if err := cfg.Set("display.confidence", "false"); err != nil || cfg.Display.Confidence {
		t.Fatalf("display confidence = %#v, %v", cfg.Display, err)
	}
	if err := cfg.Set("display.risk", "invalid"); err == nil {
		t.Fatal("expected display value error")
	}
}

func TestRuleExceptionCRUD(t *testing.T) {
	cfg := Default()
	if err := cfg.AddRuleException(RuleException{ID: "skip-git", Command: "git sttaus"}); err != nil || !cfg.HasRuleException("git sttaus") {
		t.Fatalf("add exception = %#v, %v", cfg.RuleExceptions, err)
	}
	if err := cfg.AddRuleException(RuleException{ID: "skip-git", Command: "git statsu"}); err == nil {
		t.Fatal("expected duplicate id error")
	}
	if err := cfg.UpdateRuleException("skip-git", "git statsu"); err != nil || cfg.HasRuleException("git sttaus") || !cfg.HasRuleException("git statsu") {
		t.Fatalf("update exception = %#v, %v", cfg.RuleExceptions, err)
	}
	if err := cfg.RemoveRuleException("skip-git"); err != nil || len(cfg.RuleExceptions) != 0 {
		t.Fatalf("remove exception = %#v, %v", cfg.RuleExceptions, err)
	}
	if err := cfg.RemoveRuleException("skip-git"); err == nil {
		t.Fatal("expected missing exception error")
	}
}

func TestRuleExceptionsRejectInvalidValues(t *testing.T) {
	for _, exception := range []RuleException{
		{ID: "", Command: "git status"},
		{ID: "Invalid", Command: "git status"},
		{ID: "skip", Command: " "},
		{ID: "skip", Command: strings.Repeat("x", maxRuleExceptionCommandBytes+1)},
	} {
		cfg := Default()
		if err := cfg.AddRuleException(exception); err == nil {
			t.Fatalf("accepted invalid exception %#v", exception)
		}
	}
}

func TestDefaultIsNonBlocking(t *testing.T) {
	if Default().Mode != "hint" {
		t.Fatal("default must be hint")
	}
}

func TestRemovedRegistrySettingsAreIgnoredOnDiskAndRejectedBySet(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{"schema_version":2,"registry_enabled":true,"auto_update_enabled":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := LoadGlobal(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"registry_enabled", "auto_update_enabled"} {
		if err := cfg.Set(key, "true"); err == nil {
			t.Fatalf("accepted removed setting %q", key)
		}
	}
	if err := Write(path, cfg); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "registry_enabled") || strings.Contains(string(data), "auto_update_enabled") {
		t.Fatalf("removed settings persisted: %s", data)
	}
}

func TestRemovedRegistrySessionOverridesAreIgnored(t *testing.T) {
	values, err := sessionValues(Paths{Environ: func() []string {
		return []string{"CLOSE_ENOUGH_REGISTRY_ENABLED=true", "CLOSE_ENOUGH_AUTO_UPDATE_ENABLED=true"}
	}})
	if err != nil || len(values) != 0 {
		t.Fatalf("session values = %#v, %v", values, err)
	}
}

func TestDefaultPolicyIsHintOnly(t *testing.T) {
	cfg := Default()
	if cfg.Mode != "hint" || cfg.AutoApplySafe || !cfg.CuratedPacksEnabled || cfg.CuratedAutoCorrect || cfg.RiskInterrupt || cfg.LocalLearningEnabled || cfg.LearningRetentionDays != defaultLearningRetentionDays || cfg.LearnedRuleActionCeiling != "hint" || !cfg.UndoEnabled || cfg.UndoTTLSeconds != defaultUndoTTLSeconds {
		t.Fatalf("unexpected defaults: %#v", cfg)
	}
}

func TestSetV1PolicySettings(t *testing.T) {
	cfg := Default()
	for key, value := range map[string]string{
		"curated_packs_enabled":       "false",
		"curated_auto_correct":        "false",
		"risk_interrupt":              "false",
		"local_learning_enabled":      "true",
		"learning_retention_days":     "45",
		"learned_rule_action_ceiling": "rewrite",
		"undo_enabled":                "false",
		"undo_ttl_seconds":            "45",
	} {
		if err := cfg.Set(key, value); err != nil {
			t.Fatalf("Set(%q, %q) = %v", key, value, err)
		}
	}
	if cfg.CuratedPacksEnabled || cfg.CuratedAutoCorrect || cfg.RiskInterrupt || !cfg.LocalLearningEnabled || cfg.LearningRetentionDays != 45 || cfg.LearnedRuleActionCeiling != "rewrite" || cfg.UndoEnabled || cfg.UndoTTLSeconds != 45 {
		t.Fatalf("unexpected configured policy: %#v", cfg)
	}
	if err := cfg.Set("learning_retention_days", "91"); err == nil {
		t.Fatal("accepted excessive retention")
	}
	if err := cfg.Set("learned_rule_action_ceiling", "interrupt"); err == nil {
		t.Fatal("accepted unsupported learned-rule action")
	}
	if err := cfg.Set("undo_ttl_seconds", "301"); err == nil {
		t.Fatal("accepted excessive undo ttl")
	}
}

func TestCuratedPackEnablementSessionOverride(t *testing.T) {
	cfg, err := ApplySessionOverrides(Default(), map[string]string{"CLOSE_ENOUGH_CURATED_PACKS_ENABLED": "false"})
	if err != nil || cfg.CuratedPacksEnabled {
		t.Fatalf("curated pack session override = %#v, %v", cfg, err)
	}
}

func TestHistoryKeysRequireLocalHistoryOptIn(t *testing.T) {
	if _, err := Default().HistoryKeys(nil).Generate(); !errors.Is(err, credential.ErrDisabled) {
		t.Fatalf("default history key error = %v", err)
	}
}

func TestHistoryRankerRequiresLocalHistoryOptIn(t *testing.T) {
	if _, err := Default().HistoryRanker(nil).Score(context.Background(), "git"); err != nil {
		t.Fatalf("default ranker error = %v", err)
	}
	cfg := Default()
	cfg.LocalHistoryEnabled = true
	if _, err := cfg.HistoryRanker(nil).Score(context.Background(), "git"); !errors.Is(err, history.ErrUnavailable) {
		t.Fatalf("enabled ranker error = %v", err)
	}
}

func TestGlobalPathPrefersAbsoluteXDGConfigHome(t *testing.T) {
	home := func() (string, error) { return "/home/unused", nil }
	base := filepath.Join(t.TempDir(), "config")
	path, err := globalPath(home, func(string) string { return base })
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(base, "close-enough", "config.json")
	if path != want {
		t.Fatalf("path = %q, want %q", path, want)
	}
}

func TestGlobalPathIgnoresRelativeXDGConfigHome(t *testing.T) {
	home := func() (string, error) { return filepath.Join(string(filepath.Separator), "home", "user"), nil }
	path, err := globalPath(home, func(string) string { return "relative-config" })
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(string(filepath.Separator), "home", "user", ".config", "close-enough", "config.json")
	if path != want {
		t.Fatalf("path = %q, want %q", path, want)
	}
}

func TestGlobalPathPropagatesHomeFailure(t *testing.T) {
	want := errors.New("home unavailable")
	_, err := globalPath(func() (string, error) { return "", want }, func(string) string { return "" })
	if !errors.Is(err, want) {
		t.Fatalf("error = %v, want %v", err, want)
	}
}

func TestLoadUsesProvidedXDGConfigHome(t *testing.T) {
	base := t.TempDir()
	path := filepath.Join(base, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"mode":"off"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(Paths{
		Home: func() (string, error) { return t.TempDir(), nil },
		CWD:  func() (string, error) { return t.TempDir(), nil },
		Env: func(key string) string {
			if key == "XDG_CONFIG_HOME" {
				return base
			}
			return ""
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "off" {
		t.Fatalf("mode = %q, want off", cfg.Mode)
	}
}

func TestApplySessionOverridesUsesStrictAllowlist(t *testing.T) {
	cfg, err := ApplySessionOverrides(Default(), map[string]string{
		"CLOSE_ENOUGH_MODE":                  "rewrite",
		"CLOSE_ENOUGH_AUTO_APPLY_SAFE":       "true",
		"CLOSE_ENOUGH_LOCAL_HISTORY_ENABLED": "true",
		"CLOSE_ENOUGH_UNDO_ENABLED":          "false",
		"CLOSE_ENOUGH_UNDO_TTL_SECONDS":      "45",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "rewrite" || !cfg.AutoApplySafe || !cfg.LocalHistoryEnabled || cfg.UndoEnabled || cfg.UndoTTLSeconds != 45 {
		t.Fatalf("unexpected override result: %#v", cfg)
	}
}

func TestApplySessionOverridesRejectsUnknownAndInvalidValues(t *testing.T) {
	for name, values := range map[string]map[string]string{
		"unknown":  {"CLOSE_ENOUGH_UNSAFE": "true"},
		"boolean":  {"CLOSE_ENOUGH_AUTO_APPLY_SAFE": "1"},
		"mode":     {"CLOSE_ENOUGH_MODE": "unsafe"},
		"undo ttl": {"CLOSE_ENOUGH_UNDO_TTL_SECONDS": "0"},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := ApplySessionOverrides(Default(), values); err == nil {
				t.Fatal("expected override error")
			}
		})
	}
}

func TestSessionValuesRejectsDuplicateOverrides(t *testing.T) {
	_, err := sessionValues(Paths{Environ: func() []string {
		return []string{"CLOSE_ENOUGH_MODE=hint", "CLOSE_ENOUGH_MODE=rewrite"}
	}})
	if err == nil || !strings.Contains(err.Error(), "duplicate session override") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestLoadAppliesSessionOverrides(t *testing.T) {
	cfg, err := Load(Paths{
		Home: func() (string, error) { return t.TempDir(), nil },
		CWD:  func() (string, error) { return t.TempDir(), nil },
		Env:  func(string) string { return "" },
		Environ: func() []string {
			return []string{"CLOSE_ENOUGH_MODE=interrupt"}
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "interrupt" {
		t.Fatalf("mode = %q, want interrupt", cfg.Mode)
	}
}

func TestSessionOverridesDoNotPersist(t *testing.T) {
	base := t.TempDir()
	path := filepath.Join(base, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"mode":"hint"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	paths := Paths{
		Home: func() (string, error) { return base, nil },
		CWD:  func() (string, error) { return t.TempDir(), nil },
		Env: func(key string) string {
			if key == "XDG_CONFIG_HOME" {
				return base
			}
			return ""
		},
		Environ: func() []string { return []string{"CLOSE_ENOUGH_MODE=interrupt"} },
	}
	withOverride, err := Load(paths)
	if err != nil || withOverride.Mode != "interrupt" {
		t.Fatalf("session configuration = %#v, %v", withOverride, err)
	}
	paths.Environ = func() []string { return nil }
	withoutOverride, err := Load(paths)
	if err != nil || withoutOverride.Mode != "hint" {
		t.Fatalf("persisted configuration = %#v, %v", withoutOverride, err)
	}
}

func TestSessionOverridesTakePrecedenceOverApprovedProjectAndGlobalConfig(t *testing.T) {
	root := t.TempDir()
	configHome := filepath.Join(root, "config")
	globalPath := filepath.Join(configHome, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(globalPath), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(globalPath, []byte(`{"mode":"hint","auto_apply_safe":false}`), 0o600); err != nil {
		t.Fatal(err)
	}
	project := filepath.Join(root, "project")
	writeProjectConfig(t, project, "rewrite", true)
	projectPath := filepath.Join(project, ".close-enough", "config.json")
	if err := os.WriteFile(projectPath, []byte(`{"mode":"rewrite","auto_apply_safe":true}`), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(Paths{
		Home: func() (string, error) { return root, nil },
		CWD:  func() (string, error) { return project, nil },
		Env: func(key string) string {
			if key == "XDG_CONFIG_HOME" {
				return configHome
			}
			return ""
		},
		Environ: func() []string { return []string{"CLOSE_ENOUGH_MODE=interrupt", "CLOSE_ENOUGH_AUTO_APPLY_SAFE=false"} },
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "interrupt" || cfg.AutoApplySafe {
		t.Fatalf("session precedence configuration = %#v", cfg)
	}
}

func TestLoadDiscoversNearestTrustedProjectConfiguration(t *testing.T) {
	root := t.TempDir()
	parent := filepath.Join(root, "parent")
	child := filepath.Join(parent, "child")
	if err := os.MkdirAll(child, 0o700); err != nil {
		t.Fatal(err)
	}
	writeProjectConfig(t, parent, "rewrite", true)
	writeProjectConfig(t, child, "off", true)
	cfg, err := loadFromDirectory(t, child)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "off" {
		t.Fatalf("mode = %q, want off", cfg.Mode)
	}
}

func TestLoadSkipsUntrustedProjectConfiguration(t *testing.T) {
	root := t.TempDir()
	parent := filepath.Join(root, "parent")
	child := filepath.Join(parent, "child")
	if err := os.MkdirAll(child, 0o700); err != nil {
		t.Fatal(err)
	}
	writeProjectConfig(t, parent, "rewrite", true)
	writeProjectConfig(t, child, "off", false)
	cfg, err := loadFromDirectory(t, child)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "rewrite" {
		t.Fatalf("mode = %q, want rewrite", cfg.Mode)
	}
}

func TestApprovedProjectConfigurationOverridesOnlySpecifiedFields(t *testing.T) {
	directory := t.TempDir()
	writeProjectConfig(t, directory, "hint", true)
	path := filepath.Join(directory, ".close-enough", "config.json")
	if err := os.WriteFile(path, []byte(`{"mode":"rewrite","display":{"trace":true},"auto_apply_safe":false}`), 0o600); err != nil {
		t.Fatal(err)
	}
	base := Default()
	base.Mode, base.AutoApplySafe, base.Display.Trace = "interrupt", true, false
	merged, err := mergeApprovedProject(base, path)
	if err != nil {
		t.Fatal(err)
	}
	if merged.Mode != "rewrite" || merged.AutoApplySafe || !merged.Display.Trace || !merged.Display.Cause {
		t.Fatalf("merged configuration = %#v", merged)
	}
}

func TestUnapprovedProjectConfigurationCannotOverrideGlobalConfiguration(t *testing.T) {
	directory := t.TempDir()
	writeProjectConfig(t, directory, "rewrite", false)
	path := filepath.Join(directory, ".close-enough", "config.json")
	base := Default()
	base.Mode = "interrupt"
	merged, err := mergeApprovedProject(base, path)
	if err != nil || !reflect.DeepEqual(merged, base) {
		t.Fatalf("unapproved merge = %#v, %v", merged, err)
	}
}

func TestProjectPathRejectsNonRegularConfiguration(t *testing.T) {
	directory := t.TempDir()
	configPath := filepath.Join(directory, ".close-enough", "config.json")
	if err := os.MkdirAll(configPath, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, ok := projectPath(directory); ok {
		t.Fatal("expected non-regular config to be ignored")
	}
}

func TestTrustedProjectRejectsInsecureMarkers(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission mutation uses POSIX mode bits")
	}
	directory := t.TempDir()
	writeProjectConfig(t, directory, "hint", true)
	configPath := filepath.Join(directory, ".close-enough", "config.json")
	marker := filepath.Join(directory, ".close-enough", "trusted")
	if !trustedProject(configPath) {
		t.Fatal("expected secure marker to be trusted")
	}
	if err := os.Chmod(marker, 0o644); err != nil {
		t.Fatal(err)
	}
	if trustedProject(configPath) {
		t.Fatal("expected world-readable marker to be rejected")
	}
	if err := os.Chmod(marker, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Dir(marker), 0o770); err != nil {
		t.Fatal(err)
	}
	if trustedProject(configPath) {
		t.Fatal("expected group-writable marker directory to be rejected")
	}
}

func TestTrustedProjectRejectsSymlinkMarker(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation requires additional Windows privileges")
	}
	directory := t.TempDir()
	writeProjectConfig(t, directory, "hint", true)
	configPath := filepath.Join(directory, ".close-enough", "config.json")
	marker := filepath.Join(directory, ".close-enough", "trusted")
	target := filepath.Join(directory, "target")
	if err := os.WriteFile(target, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(marker); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, marker); err != nil {
		t.Fatal(err)
	}
	if trustedProject(configPath) {
		t.Fatal("expected symlink marker to be rejected")
	}
}

func TestTrustedProjectPermissionRegressionCorpus(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("permission mutation uses POSIX mode bits")
	}
	data, err := os.ReadFile("testdata/trusted_project_permissions.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []trustedProjectFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("trusted project corpus is empty")
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			if fixture.Name == "" || fixture.Config == "" || fixture.Marker == "" || fixture.DirectoryMode == "" || fixture.Mode == "" {
				t.Fatalf("invalid trusted project fixture: %#v", fixture)
			}
			directory := t.TempDir()
			configDirectory := filepath.Join(directory, ".close-enough")
			if err := os.MkdirAll(configDirectory, 0o700); err != nil {
				t.Fatal(err)
			}
			configPath := filepath.Join(configDirectory, "config.json")
			target := filepath.Join(directory, "target")
			if fixture.Config == "file" {
				mode := projectPermission(t, fixture.ConfigMode)
				if err := os.WriteFile(configPath, []byte(`{"mode":"rewrite"}`), mode); err != nil {
					t.Fatal(err)
				}
				if err := os.Chmod(configPath, mode); err != nil {
					t.Fatal(err)
				}
			} else if fixture.Config == "symlink" {
				if err := os.WriteFile(target, []byte(`{"mode":"rewrite"}`), 0o600); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, configPath); err != nil {
					t.Fatal(err)
				}
			} else {
				t.Fatalf("unknown config type %q", fixture.Config)
			}
			marker := filepath.Join(configDirectory, "trusted")
			switch fixture.Marker {
			case "file":
				mode := projectPermission(t, fixture.MarkerMode)
				if err := os.WriteFile(marker, nil, mode); err != nil {
					t.Fatal(err)
				}
				if err := os.Chmod(marker, mode); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.WriteFile(target, nil, 0o600); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, marker); err != nil {
					t.Fatal(err)
				}
			case "missing":
			default:
				t.Fatalf("unknown marker type %q", fixture.Marker)
			}
			if err := os.Chmod(configDirectory, projectPermission(t, fixture.DirectoryMode)); err != nil {
				t.Fatal(err)
			}
			if got := trustedProject(configPath); got != fixture.Trusted {
				t.Fatalf("trustedProject(%q) = %t, want %t", configPath, got, fixture.Trusted)
			}
			base := Default()
			merged, err := mergeApprovedProject(base, configPath)
			if err != nil || merged.Mode != fixture.Mode {
				t.Fatalf("mergeApprovedProject() = %#v, %v; want mode %q", merged, err, fixture.Mode)
			}
		})
	}
}

func projectPermission(t *testing.T, value string) os.FileMode {
	t.Helper()
	parsed, err := strconv.ParseUint(value, 8, 32)
	if err != nil {
		t.Fatal(err)
	}
	return os.FileMode(parsed)
}

func loadFromDirectory(t *testing.T, directory string) (Config, error) {
	t.Helper()
	return Load(Paths{
		Home:    func() (string, error) { return t.TempDir(), nil },
		CWD:     func() (string, error) { return directory, nil },
		Env:     func(string) string { return "" },
		Environ: func() []string { return nil },
	})
}

func writeProjectConfig(t *testing.T, directory, mode string, trusted bool) {
	t.Helper()
	configDirectory := filepath.Join(directory, ".close-enough")
	if err := os.MkdirAll(configDirectory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(configDirectory, "config.json"), []byte(`{"mode":"`+mode+`"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if trusted {
		if err := os.WriteFile(filepath.Join(configDirectory, "trusted"), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDecodeMigratesVersionlessConfiguration(t *testing.T) {
	cfg, err := decode([]byte(`{"mode":"rewrite"}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SchemaVersion != CurrentSchemaVersion || cfg.Mode != "rewrite" {
		t.Fatalf("unexpected migrated config: %#v", cfg)
	}
}

func TestDecodeAcceptsCurrentConfigurationSchema(t *testing.T) {
	cfg, err := decode([]byte(`{"schema_version":`+strconv.Itoa(CurrentSchemaVersion)+`,"mode":"off"}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SchemaVersion != CurrentSchemaVersion || cfg.Mode != "off" {
		t.Fatalf("unexpected decoded config: %#v", cfg)
	}
}

func TestDecodeRejectsUnsupportedConfigurationSchema(t *testing.T) {
	_, err := decode([]byte(`{"schema_version":`+strconv.Itoa(CurrentSchemaVersion+1)+`}`), Default())
	if err == nil || !strings.Contains(err.Error(), "unsupported configuration schema version") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestDecodeValidatesGlobalConfigurationSchema(t *testing.T) {
	cfg, err := decode([]byte(`{"schema_version":1,"display":{"trace":true},"auto_apply_safe":true}`), Default())
	if err != nil || !cfg.Display.Trace || !cfg.AutoApplySafe || !cfg.Display.Cause {
		t.Fatalf("decoded configuration = %#v, %v", cfg, err)
	}
	for _, data := range []string{
		`null`,
		`{"schema_version":null}`,
		`{"schema_version":"1"}`,
		`{"auto_apply_safe":"true"}`,
		`{"undo_ttl_seconds":0}`,
		`{"unexpected":true}`,
		`{"display":{"unexpected":true}}`,
		`{"rule_exceptions":[{"id":"Invalid","command":"git status"}]}`,
		`{"rule_exceptions":[{"id":"skip-one","command":"git status"},{"id":"skip-two","command":"git status"}]}`,
	} {
		if _, err := decode([]byte(data), Default()); err == nil {
			t.Fatalf("accepted invalid configuration %s", data)
		}
	}
}

func TestWriteAtomicallyReplacesConfigWithRestrictivePermissions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{"mode":"off"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg := Default()
	cfg.Mode = "rewrite"
	if err := Write(path, cfg); err != nil {
		t.Fatal(err)
	}
	loaded, err := LoadGlobal(path)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Mode != "rewrite" {
		t.Fatalf("mode = %q, want rewrite", loaded.Mode)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Fatalf("permissions = %o, want 600", info.Mode().Perm())
	}
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".config.json.tmp-") {
			t.Fatalf("temporary file remains: %s", entry.Name())
		}
	}
}

func TestWriteRemovesTemporaryFileAfterRenameFailure(t *testing.T) {
	directory := t.TempDir()
	if err := Write(directory, Default()); err == nil {
		t.Fatal("expected rename failure")
	}
	entries, err := os.ReadDir(filepath.Dir(directory))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), "."+filepath.Base(directory)+".tmp-") {
			t.Fatalf("temporary file remains: %s", entry.Name())
		}
	}
}
