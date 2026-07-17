package main

import (
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gongahkia/close-enough/internal/clierr"
	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/runtimecheck"
)

func TestRunExitCodes(t *testing.T) {
	tests := []struct {
		name  string
		setup func(*testing.T)
		args  []string
		want  int
	}{
		{name: "success", args: []string{"version"}, want: clierr.ExitSuccess},
		{name: "usage", args: []string{"check"}, want: clierr.ExitUsage},
		{
			name: "configuration",
			setup: func(t *testing.T) {
				path := filepath.Join(t.TempDir(), "close-enough", "config.json")
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte("{"), 0o600); err != nil {
					t.Fatal(err)
				}
				t.Setenv("XDG_CONFIG_HOME", filepath.Dir(filepath.Dir(path)))
			},
			args: []string{"config", "show"}, want: clierr.ExitConfiguration,
		},
		{name: "input", args: []string{"pack", "validate", "missing-pack.json"}, want: clierr.ExitInput},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			t.Setenv("XDG_CONFIG_HOME", t.TempDir())
			if test.setup != nil {
				test.setup(t)
			}
			err := run(test.args, io.Discard, io.Discard)
			if got := clierr.Code(err); got != test.want {
				t.Fatalf("run(%q) code = %d, want %d (err %v)", test.args, got, test.want, err)
			}
		})
	}
}

func TestRunClassifiesOutputFailures(t *testing.T) {
	err := run([]string{"version"}, failingWriter{}, io.Discard)
	if got := clierr.Code(err); got != clierr.ExitOperation {
		t.Fatalf("output failure code = %d, want %d", got, clierr.ExitOperation)
	}
}

func TestProcessExitCodes(t *testing.T) {
	binary := filepath.Join(t.TempDir(), "close-enough")
	build := exec.Command("go", "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", binary, ".")
	if data, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build process test binary: %v\n%s", err, data)
	}
	configHome := t.TempDir()
	invalidConfigHome := t.TempDir()
	path := filepath.Join(invalidConfigHome, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name       string
		args       []string
		configHome string
		want       int
	}{
		{name: "success", args: []string{"version"}, configHome: configHome, want: clierr.ExitSuccess},
		{name: "usage", args: []string{"check"}, configHome: configHome, want: clierr.ExitUsage},
		{name: "configuration", args: []string{"config", "show"}, configHome: invalidConfigHome, want: clierr.ExitConfiguration},
		{name: "input", args: []string{"pack", "validate", "missing-pack.json"}, configHome: configHome, want: clierr.ExitInput},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			command := exec.Command(binary, test.args...)
			command.Env = append(os.Environ(), "XDG_CONFIG_HOME="+test.configHome)
			_, err := command.CombinedOutput()
			if test.want == clierr.ExitSuccess {
				if err != nil {
					t.Fatal(err)
				}
				return
			}
			var exitError *exec.ExitError
			if !errors.As(err, &exitError) {
				t.Fatalf("process error = %v, want exit code %d", err, test.want)
			}
			if got := exitError.ExitCode(); got != test.want {
				t.Fatalf("exit code = %d, want %d", got, test.want)
			}
		})
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, errors.New("write failure") }

func TestUsageWritesUsage(t *testing.T) {
	var output strings.Builder
	err := run(nil, io.Discard, &output)
	if clierr.Code(err) != clierr.ExitUsage || !strings.HasPrefix(output.String(), "usage: ") {
		t.Fatalf("unexpected usage result: %d, %q", clierr.Code(err), output.String())
	}
}

func TestVersionStringUsesInjectedBuildMetadata(t *testing.T) {
	originalVersion, originalCommit := version, commit
	t.Cleanup(func() { version, commit = originalVersion, originalCommit })
	version, commit = "v1.2.3", "abc123"
	if got := versionString(); got != "close-enough v1.2.3 (abc123)" {
		t.Fatalf("versionString() = %q", got)
	}
	commit = "unknown"
	if got := versionString(); got != "close-enough v1.2.3" {
		t.Fatalf("versionString() = %q", got)
	}
}

func TestCheckJSONIncludesStageWithoutRawCommand(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"check", "--command", "gti --token=super-secret"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	value := output.String()
	if !strings.Contains(value, `"stage":"pre"`) || strings.Contains(value, "super-secret") || strings.Contains(value, `"command":`) {
		t.Fatalf("unexpected diagnostic event: %s", value)
	}
}

func TestCheckIncompleteInputReturnsNoRepair(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"check", "--command", "git '"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), `"action":"none"`) || !strings.Contains(output.String(), `"incomplete":true`) || strings.Contains(output.String(), `"suggestion"`) {
		t.Fatalf("unexpected incomplete event: %s", output.String())
	}
}

func TestRenderPlainDiagnosticHonorsDisplayConfiguration(t *testing.T) {
	decision := diagnose.Decision{Cause: "unknown command", Consequence: "the shell will reject it", Suggestion: "git status", Risk: diagnose.RiskSafe, Trace: []string{"resolver:path", "distance:1"}}
	if got := renderPlainDiagnostic(decision, config.Default().Display); got != "unknown command: the shell will reject it\nDid you mean: git status\nRisk: safe\n" {
		t.Fatalf("default display = %q", got)
	}
	display := config.Display{Change: true}
	if got := renderPlainDiagnostic(decision, display); got != "Did you mean: git status\n" {
		t.Fatalf("change-only display = %q", got)
	}
	if got := renderPlainDiagnostic(decision, config.Display{}); got != "" {
		t.Fatalf("empty display = %q", got)
	}
	if got := renderPlainDiagnostic(decision, config.Display{Trace: true}); got != "Trace: resolver:path, distance:1\n" {
		t.Fatalf("trace display = %q", got)
	}
	if got := renderPlainDiagnostic(diagnose.Decision{}, config.Display{Trace: true}); got != "" {
		t.Fatalf("empty trace display = %q", got)
	}
}

func TestCheckPlainUsesConfiguredDisplayFields(t *testing.T) {
	configHome := t.TempDir()
	path := filepath.Join(configHome, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"display":{"cause":false,"change":true,"risk":false,"consequence":false}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_CONFIG_HOME", configHome)
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if got := output.String(); got != "Did you mean: git status\n" {
		t.Fatalf("plain output = %q", got)
	}
}

func TestRenderErrorEscapesTerminalControlCharacters(t *testing.T) {
	err := errors.New("invalid\x1b[31m\nnext\u0085")
	if got := renderError(err); got != "close-enough: invalid\\x1B[31m\\x0Anext\\u0085\n" {
		t.Fatalf("renderError() = %q", got)
	}
}

func TestRenderErrorPreservesSafeText(t *testing.T) {
	if got := renderError(errors.New("missing --command")); got != "close-enough: missing --command\n" {
		t.Fatalf("renderError() = %q", got)
	}
}

func TestStartupErrorFailsClosedExceptDoctor(t *testing.T) {
	report := runtimecheck.Report{Safe: false, Findings: []runtimecheck.Finding{{Code: "unsafe-path"}}}
	if err := startupError([]string{"check"}, report); err == nil {
		t.Fatal("expected unsafe startup error")
	}
	if err := startupError([]string{"doctor"}, report); err != nil {
		t.Fatalf("doctor should remain available: %v", err)
	}
}

func TestDoctorIncludesRuntimeReport(t *testing.T) {
	var output strings.Builder
	if err := run([]string{"doctor"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), `"runtime":`) {
		t.Fatalf("doctor output lacks runtime report: %s", output.String())
	}
}
