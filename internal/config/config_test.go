package config

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/credential"
	"github.com/gongahkia/close-enough/internal/featuregate"
	"github.com/gongahkia/close-enough/internal/history"
)

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

func TestDefaultIsNonBlocking(t *testing.T) {
	if Default().Mode != "hint" {
		t.Fatal("default must be hint")
	}
}

func TestFeatureGatesRequireExplicitRegistryEnablement(t *testing.T) {
	cfg := Default()
	cfg.AutoUpdateEnabled = true
	if cfg.Features().Enabled(featuregate.AutoUpdate) {
		t.Fatal("auto-update must remain disabled without registry opt-in")
	}
	cfg.RegistryEnabled = true
	if !cfg.Features().Enabled(featuregate.Registry) || !cfg.Features().Enabled(featuregate.AutoUpdate) {
		t.Fatal("explicitly enabled features must be available")
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
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Mode != "rewrite" || !cfg.AutoApplySafe || !cfg.LocalHistoryEnabled {
		t.Fatalf("unexpected override result: %#v", cfg)
	}
}

func TestApplySessionOverridesRejectsUnknownAndInvalidValues(t *testing.T) {
	for name, values := range map[string]map[string]string{
		"unknown": {"CLOSE_ENOUGH_UNSAFE": "true"},
		"boolean": {"CLOSE_ENOUGH_AUTO_APPLY_SAFE": "1"},
		"mode":    {"CLOSE_ENOUGH_MODE": "unsafe"},
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
	if err != nil || merged != base {
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
	cfg, err := decode([]byte(`{"schema_version":1,"mode":"off"}`), Default())
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SchemaVersion != CurrentSchemaVersion || cfg.Mode != "off" {
		t.Fatalf("unexpected decoded config: %#v", cfg)
	}
}

func TestDecodeRejectsUnsupportedConfigurationSchema(t *testing.T) {
	_, err := decode([]byte(`{"schema_version":2}`), Default())
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
		`{"unexpected":true}`,
		`{"display":{"unexpected":true}}`,
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
