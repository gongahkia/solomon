package config

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
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
