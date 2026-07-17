package config

import (
	"errors"
	"os"
	"path/filepath"
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
