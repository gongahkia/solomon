package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/clierr"
)

type cliHarness struct {
	binary     string
	configHome string
}

type cliResult struct {
	stdout   string
	stderr   string
	exitCode int
}

func TestCLIEndToEnd(t *testing.T) {
	harness := newCLIHarness(t)
	t.Run("version", func(t *testing.T) {
		result := harness.run(t, harness.configHome, "version")
		if result.exitCode != clierr.ExitSuccess || result.stdout != "close-enough dev\n" || result.stderr != "" {
			t.Fatalf("version result = %#v", result)
		}
	})
	t.Run("safe suggestion", func(t *testing.T) {
		result := harness.run(t, harness.configHome, "check", "--command", "git sttaus")
		if result.exitCode != clierr.ExitSuccess || result.stderr != "" {
			t.Fatalf("safe result = %#v", result)
		}
		var event struct {
			Action     string `json:"action"`
			Suggestion string `json:"suggestion"`
			Risk       string `json:"risk"`
		}
		if err := json.Unmarshal([]byte(result.stdout), &event); err != nil || event.Action != "hint" || event.Suggestion != "git status" || event.Risk != "safe" {
			t.Fatalf("safe event = %#v, %v", event, err)
		}
	})
	t.Run("high risk remains a hint", func(t *testing.T) {
		const secret = "super-secret"
		result := harness.run(t, harness.configHome, "check", "--command", "git sttaus --token="+secret)
		if result.exitCode != clierr.ExitSuccess || result.stderr != "" || strings.Contains(result.stdout, secret) {
			t.Fatalf("high-risk result = %#v", result)
		}
		var event struct {
			Action     string `json:"action"`
			Suggestion string `json:"suggestion"`
			Risk       string `json:"risk"`
		}
		if err := json.Unmarshal([]byte(result.stdout), &event); err != nil || event.Action != "hint" || event.Suggestion != "git status --token=[REDACTED]" || event.Risk != "high" {
			t.Fatalf("high-risk event = %#v, %v", event, err)
		}
	})
	t.Run("usage failure", func(t *testing.T) {
		result := harness.run(t, harness.configHome, "check")
		if result.exitCode != clierr.ExitUsage || result.stdout != "" || !strings.HasPrefix(result.stderr, "close-enough: --command is required\n") {
			t.Fatalf("usage result = %#v", result)
		}
	})
	t.Run("configuration failure", func(t *testing.T) {
		configHome := t.TempDir()
		path := filepath.Join(configHome, "close-enough", "config.json")
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("{"), 0o600); err != nil {
			t.Fatal(err)
		}
		result := harness.run(t, configHome, "config", "show")
		if result.exitCode != clierr.ExitConfiguration || result.stdout != "" || !strings.HasPrefix(result.stderr, "close-enough: ") {
			t.Fatalf("configuration result = %#v", result)
		}
	})
}

func newCLIHarness(t *testing.T) cliHarness {
	t.Helper()
	name := "close-enough"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	harness := cliHarness{binary: filepath.Join(t.TempDir(), name), configHome: t.TempDir()}
	command := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", harness.binary, ".")
	if data, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build CLI test binary: %v\n%s", err, data)
	}
	return harness
}

func (h cliHarness) run(t *testing.T, configHome string, args ...string) cliResult {
	t.Helper()
	command := exec.Command(h.binary, args...)
	command.Env = replaceHarnessEnvironment(os.Environ(), "XDG_CONFIG_HOME", configHome)
	var stdout, stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	err := command.Run()
	result := cliResult{stdout: stdout.String(), stderr: stderr.String()}
	if err == nil {
		return result
	}
	var exitError *exec.ExitError
	if !errors.As(err, &exitError) {
		t.Fatal(err)
	}
	result.exitCode = exitError.ExitCode()
	return result
}

func replaceHarnessEnvironment(environment []string, key, value string) []string {
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		entryKey, _, _ := strings.Cut(entry, "=")
		if runtime.GOOS == "windows" && strings.EqualFold(entryKey, key) || runtime.GOOS != "windows" && entryKey == key {
			continue
		}
		result = append(result, entry)
	}
	return append(result, key+"="+value)
}
