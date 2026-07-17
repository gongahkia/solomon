package main

import (
	"encoding/json"
	"errors"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode"

	"github.com/gongahkia/close-enough/internal/clierr"
	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/runtimecheck"
)

type terminalEscapeFixture struct {
	Name    string `json:"name"`
	Payload string `json:"payload"`
	Want    string `json:"want"`
}

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
	decision := diagnose.Decision{Cause: "unknown command", Consequence: "the shell will reject it", Suggestion: "git status", Confidence: 0.85, Risk: diagnose.RiskSafe, Trace: []string{"resolver:path", "distance:1"}}
	if got := renderPlainDiagnostic(decision, config.Default().Display, ""); got != "unknown command: the shell will reject it\nDid you mean: git status\nConfidence: medium\nRisk: safe\n" {
		t.Fatalf("default display = %q", got)
	}
	display := config.Display{Change: true}
	if got := renderPlainDiagnostic(decision, display, ""); got != "Did you mean: git status\n" {
		t.Fatalf("change-only display = %q", got)
	}
	if got := renderPlainDiagnostic(decision, config.Display{}, ""); got != "" {
		t.Fatalf("empty display = %q", got)
	}
	if got := renderPlainDiagnostic(decision, config.Display{Trace: true}, ""); got != "Trace: resolver:path, distance:1\n" {
		t.Fatalf("trace display = %q", got)
	}
	if got := renderPlainDiagnostic(diagnose.Decision{}, config.Display{Trace: true}, ""); got != "no suggestion\n" {
		t.Fatalf("empty trace display = %q", got)
	}
	unsafe := diagnose.Decision{Cause: "bad\x1b", Consequence: "next\nline", Suggestion: "git\tstatus", Confidence: 0.95, Risk: diagnose.RiskSafe}
	if got := renderPlainDiagnostic(unsafe, config.Default().Display, ""); got != "bad\\x1B: next\\x0Aline\nDid you mean: git\\x09status\nConfidence: high\nRisk: safe\n" {
		t.Fatalf("sanitized display = %q", got)
	}
}

func TestConfidencePresentation(t *testing.T) {
	for _, test := range []struct {
		confidence float64
		want       string
	}{
		{0.90, "high"},
		{0.80, "medium"},
		{0.79, "low"},
		{-0.01, "unknown"},
		{math.NaN(), "unknown"},
	} {
		if got := confidencePresentation(test.confidence); got != test.want {
			t.Fatalf("confidencePresentation(%v) = %q, want %q", test.confidence, got, test.want)
		}
	}
}

func TestRenderRiskRationale(t *testing.T) {
	decision := diagnose.Decision{Suggestion: "rm file", Risk: diagnose.RiskHigh, RiskRationale: "may modify the filesystem"}
	display := config.Display{Risk: true}
	if got, want := renderPlainDiagnostic(decision, display, ""), "Risk: high\nRisk rationale: may modify the filesystem\n"; got != want {
		t.Fatalf("risk rationale output = %q, want %q", got, want)
	}
	if got := renderScreenReaderDiagnostic(decision, display); !strings.Contains(got, "Risk rationale: may modify the filesystem") {
		t.Fatalf("screen-reader rationale output = %q", got)
	}
}

func TestRenderPlainDiagnosticColorMode(t *testing.T) {
	decision := diagnose.Decision{Suggestion: "git status", Risk: diagnose.RiskSafe}
	colored := renderPlainDiagnosticWithColor(decision, config.Display{Change: true, Risk: true}, "", true)
	if got, want := colored, "\x1b[32mDid you mean: \x1b[0mgit status\n\x1b[33mRisk: \x1b[0msafe\n"; got != want {
		t.Fatalf("colored output = %q, want %q", got, want)
	}
	plain := renderPlainDiagnosticWithColor(decision, config.Display{Change: true, Risk: true}, "", false)
	if strings.Contains(plain, "\x1b[") {
		t.Fatalf("color-disabled output contains ANSI sequence: %q", plain)
	}
}

func TestDiagnosticColorEnabled(t *testing.T) {
	tests := []struct {
		name string
		mode string
		env  map[string]string
		want bool
		err  bool
	}{
		{name: "never", mode: colorNever},
		{name: "always", mode: colorAlways, want: true},
		{name: "auto non-terminal", mode: colorAuto},
		{name: "auto no color", mode: colorAuto, env: map[string]string{"NO_COLOR": "1"}},
		{name: "invalid", mode: "invalid", err: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := diagnosticColorEnabled(test.mode, io.Discard, func(key string) string { return test.env[key] })
			if (err != nil) != test.err || got != test.want {
				t.Fatalf("diagnosticColorEnabled() = %t, %v; want %t, error=%t", got, err, test.want, test.err)
			}
		})
	}
}

func TestCheckColorNeverDisablesANSI(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	for _, color := range []string{colorAlways, colorNever} {
		var output strings.Builder
		if err := run([]string{"check", "--format", "plain", "--color", color, "--command", "git sttaus"}, &output, io.Discard); err != nil {
			t.Fatal(err)
		}
		hasANSI := strings.Contains(output.String(), "\x1b[")
		if hasANSI != (color == colorAlways) {
			t.Fatalf("--color=%s ANSI output = %q", color, output.String())
		}
	}
	if err := run([]string{"check", "--color", "invalid", "--command", "git sttaus"}, io.Discard, io.Discard); err == nil {
		t.Fatal("expected invalid color error")
	}
}

func TestRenderScreenReaderDiagnostic(t *testing.T) {
	decision := diagnose.Decision{
		Cause:       "unknown command",
		Consequence: "the shell will reject it",
		Suggestion:  "git status",
		Confidence:  0.85,
		Risk:        diagnose.RiskSafe,
		Trace:       []string{"resolver:path", "distance:1"},
	}
	display := config.Display{Cause: true, Change: true, Confidence: true, Risk: true, Consequence: true, Trace: true}
	want := "Cause: unknown command\nConsequence: the shell will reject it\nSuggested command: git status\nConfidence level: medium\nRisk level: safe\nTrace: resolver:path; distance:1\n"
	if got := renderScreenReaderDiagnostic(decision, display); got != want {
		t.Fatalf("screen-reader output = %q, want %q", got, want)
	}
	if got := renderScreenReaderDiagnostic(diagnose.Decision{}, display); got != "No suggestion.\n" {
		t.Fatalf("empty screen-reader output = %q", got)
	}
	if got := renderScreenReaderDiagnostic(decision, config.Display{Change: true}); strings.Contains(got, "\x1b[") || strings.Contains(got, "[-") {
		t.Fatalf("screen-reader output contains visual markup: %q", got)
	}
}

func TestCheckScreenReaderMode(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--color", "always", "--screen-reader", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if got := output.String(); strings.Contains(got, "\x1b[") || strings.Contains(got, "[-") || !strings.Contains(got, "Suggested command: git status") {
		t.Fatalf("screen-reader command output = %q", got)
	}
	if err := run([]string{"check", "--format", "json", "--screen-reader", "--command", "git sttaus"}, io.Discard, io.Discard); err == nil {
		t.Fatal("expected screen-reader format error")
	}
}

func TestCheckPlainUsesConfiguredDisplayFields(t *testing.T) {
	configHome := t.TempDir()
	path := filepath.Join(configHome, "close-enough", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"display":{"cause":false,"change":true,"confidence":false,"risk":false,"consequence":false}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_CONFIG_HOME", configHome)
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if got := output.String(); got != "Did you mean: git status\ngit [-sttaus-]{+status+}\n" {
		t.Fatalf("plain output = %q", got)
	}
}

func TestRuleCommandCRUD(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"rule", "list"}, &output, io.Discard); err != nil || output.String() != "[]\n" {
		t.Fatalf("empty rule list = %q, %v", output.String(), err)
	}
	if err := run([]string{"rule", "add", "skip-git", "git sttaus"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	output.Reset()
	if err := run([]string{"rule", "list"}, &output, io.Discard); err != nil || output.String() != "[{\"id\":\"skip-git\",\"command\":\"git sttaus\"}]\n" {
		t.Fatalf("created rule list = %q, %v", output.String(), err)
	}
	output.Reset()
	if err := run([]string{"check", "--command", "git sttaus"}, &output, io.Discard); err != nil || !strings.Contains(output.String(), `"action":"none"`) || strings.Contains(output.String(), `"suggestion"`) {
		t.Fatalf("suppressed diagnostic = %q, %v", output.String(), err)
	}
	if err := run([]string{"rule", "update", "skip-git", "git statsu"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	if err := run([]string{"rule", "remove", "skip-git"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	output.Reset()
	if err := run([]string{"rule", "list"}, &output, io.Discard); err != nil || output.String() != "[]\n" {
		t.Fatalf("removed rule list = %q, %v", output.String(), err)
	}
}

func TestRuleCommandRejectsInvalidMutations(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	for _, args := range [][]string{
		{"rule", "add", "Invalid", "git sttaus"},
		{"rule", "update", "missing", "git sttaus"},
		{"rule", "remove", "missing"},
	} {
		if err := run(args, io.Discard, io.Discard); err == nil {
			t.Fatalf("accepted invalid rule command %q", args)
		}
	}
}

func TestInspectDecisionCommand(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"inspect-decision", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	value := output.String()
	if !strings.Contains(value, `"stage":"pre"`) || !strings.Contains(value, `"suggestion":"git status"`) || !strings.Contains(value, `"diff":"- git sttaus\n+ git status"`) || strings.Contains(value, `"command":`) {
		t.Fatalf("inspection output = %s", value)
	}
	for _, args := range [][]string{
		{"inspect-decision", "--command", "git sttaus", "--stage", "invalid"},
		{"inspect-decision"},
	} {
		if err := run(args, io.Discard, io.Discard); err == nil {
			t.Fatalf("accepted invalid inspect command %q", args)
		}
	}
}

func TestPackDirectoryUsesAbsoluteXDGDataHome(t *testing.T) {
	base := t.TempDir()
	directory, err := packDirectory(func() (string, error) { return "/unused", nil }, func(string) string { return base })
	if err != nil || directory != filepath.Join(base, "close-enough", "packs") {
		t.Fatalf("pack directory = %q, %v", directory, err)
	}
	directory, err = packDirectory(func() (string, error) { return "/home/user", nil }, func(string) string { return "relative" })
	if err != nil || directory != "/home/user/.local/share/close-enough/packs" {
		t.Fatalf("fallback pack directory = %q, %v", directory, err)
	}
}

func TestConfigCauseToggleControlsPlainDiagnostic(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	if err := run([]string{"config", "set", "display.cause", "false"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), "unknown subcommand") || !strings.Contains(output.String(), "Did you mean: git status") {
		t.Fatalf("cause toggle output = %q", output.String())
	}
}

func TestConfigChangeToggleControlsPlainDiagnostic(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	if err := run([]string{"config", "set", "display.change", "false"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), "Did you mean:") || strings.Contains(output.String(), "[-sttaus-") {
		t.Fatalf("change toggle output = %q", output.String())
	}
}

func TestConfigRiskToggleControlsPlainDiagnostic(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	if err := run([]string{"config", "set", "display.risk", "false"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), "Risk:") {
		t.Fatalf("risk toggle output = %q", output.String())
	}
}

func TestConfigConsequenceToggleControlsPlainDiagnostic(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	if err := run([]string{"config", "set", "display.consequence", "false"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(output.String(), "the command will") || strings.Contains(output.String(), "will reject") {
		t.Fatalf("consequence toggle output = %q", output.String())
	}
}

func TestConfigTraceToggleControlsPlainDiagnostic(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	if err := run([]string{"config", "set", "display.trace", "true"}, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "git sttaus"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "Trace: pack:core-git") {
		t.Fatalf("trace toggle output = %q", output.String())
	}
}

func TestCheckPlainNoSuggestionFallback(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	var output strings.Builder
	if err := run([]string{"check", "--format", "plain", "--command", "echo unchanged"}, &output, io.Discard); err != nil {
		t.Fatal(err)
	}
	if got := output.String(); got != "no suggestion\n" {
		t.Fatalf("no-suggestion fallback = %q", got)
	}
}

func TestRenderErrorEscapesTerminalControlCharacters(t *testing.T) {
	err := errors.New("invalid\x1b[31m\nnext\u0085")
	if got := renderError(err); got != "close-enough: invalid\\x1B[31m\\x0Anext\\u0085\n" {
		t.Fatalf("renderError() = %q", got)
	}
}

func TestTerminalEscapeInjectionRegressionCorpus(t *testing.T) {
	data, err := os.ReadFile("testdata/terminal_escape_injection.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixtures []terminalEscapeFixture
	if err := json.Unmarshal(data, &fixtures); err != nil {
		t.Fatal(err)
	}
	if len(fixtures) == 0 {
		t.Fatal("terminal escape corpus is empty")
	}
	for _, fixture := range fixtures {
		t.Run(fixture.Name, func(t *testing.T) {
			if fixture.Name == "" || fixture.Payload == "" || fixture.Want == "" {
				t.Fatalf("invalid terminal escape fixture: %#v", fixture)
			}
			if got := sanitizeTerminalText(fixture.Payload); got != fixture.Want {
				t.Fatalf("sanitizeTerminalText(%q) = %q, want %q", fixture.Payload, got, fixture.Want)
			}
			for _, character := range fixture.Want {
				if unicode.IsControl(character) || unicode.Is(unicode.Bidi_Control, character) {
					t.Fatalf("sanitized output retains terminal control %U", character)
				}
			}
		})
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
