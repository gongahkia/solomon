package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"unicode"

	"github.com/gongahkia/close-enough/internal/clierr"
	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
	"github.com/gongahkia/close-enough/internal/runtimecheck"
	"github.com/gongahkia/close-enough/internal/shell"
)

var version = "dev"
var commit = "unknown"

const (
	colorAuto   = "auto"
	colorAlways = "always"
	colorNever  = "never"
)

func main() {
	args := os.Args[1:]
	if err := startupError(args, runtimecheck.Current()); err != nil {
		fmt.Fprint(os.Stderr, renderError(err))
		os.Exit(clierr.ExitOperation)
	}
	if err := run(args, os.Stdout, os.Stderr); err != nil {
		fmt.Fprint(os.Stderr, renderError(err))
		os.Exit(clierr.Code(err))
	}
}

func startupError(args []string, report runtimecheck.Report) error {
	if len(args) > 0 && args[0] == "doctor" {
		return nil
	}
	return report.Error()
}

func renderError(err error) string {
	return "close-enough: " + sanitizeTerminalText(err.Error()) + "\n"
}

func sanitizeTerminalText(value string) string {
	var output strings.Builder
	for _, character := range value {
		switch {
		case character <= 0x1f || character == 0x7f:
			fmt.Fprintf(&output, "\\x%02X", character)
		case unicode.IsControl(character):
			fmt.Fprintf(&output, "\\u%04X", character)
		default:
			output.WriteRune(character)
		}
	}
	return output.String()
}

func run(args []string, stdout, stderr io.Writer) error {
	if len(args) == 0 {
		return usage(stderr)
	}
	switch args[0] {
	case "version":
		_, err := fmt.Fprintln(stdout, versionString())
		return clierr.Wrap(clierr.Operation, err)
	case "init":
		return initCommand(args[1:], stdout)
	case "check":
		return checkCommand(args[1:], stdout)
	case "inspect-decision":
		return inspectDecisionCommand(args[1:], stdout)
	case "config":
		return configCommand(args[1:], stdout)
	case "rule":
		return ruleCommand(args[1:], stdout)
	case "pack":
		return packCommand(args[1:], stdout)
	case "doctor":
		return doctorCommand(stdout)
	default:
		return usage(stderr)
	}
}

func versionString() string {
	if commit == "" || commit == "unknown" {
		return "close-enough " + version
	}
	return "close-enough " + version + " (" + commit + ")"
}

func usage(w io.Writer) error {
	if _, err := fmt.Fprintln(w, "usage: close-enough <init|check|inspect-decision|config|rule|pack|doctor|version>"); err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	return clierr.New(clierr.Usage, "invalid command")
}

func initCommand(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	shellName := fs.String("shell", "", "shell")
	if err := fs.Parse(args); err != nil {
		return clierr.Wrap(clierr.Usage, err)
	}
	if *shellName == "" {
		return clierr.New(clierr.Usage, "--shell is required")
	}
	script, err := shell.Script(*shellName)
	if err != nil {
		return clierr.Wrap(clierr.Usage, err)
	}
	_, err = io.WriteString(stdout, script)
	return clierr.Wrap(clierr.Operation, err)
}

func checkCommand(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("check", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	command := fs.String("command", "", "command line")
	stage := fs.String("stage", "pre", "pre or post")
	format := fs.String("format", "json", "json, plain, or record")
	color := fs.String("color", colorAuto, "auto, always, or never")
	screenReader := fs.Bool("screen-reader", false, "structured ANSI-free plain output")
	if err := fs.Parse(args); err != nil {
		return clierr.Wrap(clierr.Usage, err)
	}
	if *command == "" {
		return clierr.New(clierr.Usage, "--command is required")
	}
	if *stage != "pre" && *stage != "post" {
		return clierr.New(clierr.Usage, "--stage must be pre or post")
	}
	if *color != colorAuto && *color != colorAlways && *color != colorNever {
		return clierr.New(clierr.Usage, "--color must be auto, always, or never")
	}
	if *screenReader && *format != "plain" {
		return clierr.New(clierr.Usage, "--screen-reader requires --format plain")
	}
	cfg, err := config.Load(config.Paths{Home: os.UserHomeDir, CWD: os.Getwd, Env: os.Getenv, Environ: os.Environ})
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	decision, err := diagnose.New(diagnose.Options{Config: cfg, Path: os.Getenv("PATH"), CWD: mustGetwd()}).Check(*command, *stage)
	if err != nil {
		return clierr.Wrap(clierr.Input, err)
	}
	switch *format {
	case "json":
		data, err := decision.JSON(*stage)
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		_, err = stdout.Write(append(data, '\n'))
		return clierr.Wrap(clierr.Operation, err)
	case "plain":
		colorEnabled, err := diagnosticColorEnabled(*color, stdout, os.Getenv)
		if err != nil {
			return clierr.New(clierr.Usage, err.Error())
		}
		output := renderPlainDiagnosticWithColor(decision, cfg.Display, *command, colorEnabled)
		if *screenReader {
			output = renderScreenReaderDiagnostic(decision, cfg.Display)
		}
		if len(output) > diagnose.MaxOutputBytes {
			return clierr.Wrap(clierr.Operation, diagnose.ErrOutputLimit)
		}
		_, err = fmt.Fprint(stdout, output)
		return clierr.Wrap(clierr.Operation, err)
	case "record":
		record, err := decision.Record()
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		_, err = fmt.Fprint(stdout, record)
		return clierr.Wrap(clierr.Operation, err)
	default:
		return clierr.New(clierr.Usage, "--format must be json, plain, or record")
	}
}

func inspectDecisionCommand(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("inspect-decision", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	command := fs.String("command", "", "command line")
	stage := fs.String("stage", "pre", "pre or post")
	if err := fs.Parse(args); err != nil {
		return clierr.Wrap(clierr.Usage, err)
	}
	if *command == "" {
		return clierr.New(clierr.Usage, "--command is required")
	}
	if *stage != "pre" && *stage != "post" {
		return clierr.New(clierr.Usage, "--stage must be pre or post")
	}
	cfg, err := config.Load(config.Paths{Home: os.UserHomeDir, CWD: os.Getwd, Env: os.Getenv, Environ: os.Environ})
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	decision, err := diagnose.New(diagnose.Options{Config: cfg, Path: os.Getenv("PATH"), CWD: mustGetwd()}).Check(*command, *stage)
	if err != nil {
		return clierr.Wrap(clierr.Input, err)
	}
	inspection, err := decision.Inspect(*stage, *command)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(inspection))
}

func renderPlainDiagnostic(decision diagnose.Decision, display config.Display, command string) string {
	return renderPlainDiagnosticWithColor(decision, display, command, false)
}

func renderPlainDiagnosticWithColor(decision diagnose.Decision, display config.Display, command string, colorEnabled bool) string {
	if decision.Suggestion == "" {
		return "no suggestion\n"
	}
	lines := []string{}
	if display.Cause && display.Consequence && decision.Cause != "" && decision.Consequence != "" {
		lines = append(lines, sanitizeTerminalText(decision.Cause)+": "+sanitizeTerminalText(decision.Consequence))
	} else {
		if display.Cause && decision.Cause != "" {
			lines = append(lines, diagnosticLabel("Cause: ", "36", colorEnabled)+sanitizeTerminalText(decision.Cause))
		}
		if display.Consequence && decision.Consequence != "" {
			lines = append(lines, diagnosticLabel("Consequence: ", "36", colorEnabled)+sanitizeTerminalText(decision.Consequence))
		}
	}
	if display.Change && decision.Suggestion != "" {
		lines = append(lines, diagnosticLabel("Did you mean: ", "32", colorEnabled)+sanitizeTerminalText(decision.Suggestion))
		if diff := decision.CommandDiffEmphasis(command); diff != "" {
			lines = append(lines, sanitizeTerminalText(diff))
		}
	}
	if display.Confidence {
		lines = append(lines, diagnosticLabel("Confidence: ", "35", colorEnabled)+confidencePresentation(decision.Confidence))
	}
	if display.Risk {
		lines = append(lines, diagnosticLabel("Risk: ", "33", colorEnabled)+string(decision.Risk))
		if decision.RiskRationale != "" {
			lines = append(lines, diagnosticLabel("Risk rationale: ", "33", colorEnabled)+sanitizeTerminalText(decision.RiskRationale))
		}
	}
	if display.Trace && len(decision.Trace) > 0 {
		trace := make([]string, len(decision.Trace))
		for index, value := range decision.Trace {
			trace[index] = sanitizeTerminalText(value)
		}
		lines = append(lines, diagnosticLabel("Trace: ", "36", colorEnabled)+strings.Join(trace, ", "))
	}
	if len(lines) == 0 {
		return ""
	}
	return strings.Join(lines, "\n") + "\n"
}

func confidencePresentation(confidence float64) string {
	switch {
	case math.IsNaN(confidence), math.IsInf(confidence, 0), confidence < 0, confidence > 1:
		return "unknown"
	case confidence >= 0.90:
		return "high"
	case confidence >= 0.80:
		return "medium"
	default:
		return "low"
	}
}

func renderScreenReaderDiagnostic(decision diagnose.Decision, display config.Display) string {
	if decision.Suggestion == "" {
		return "No suggestion.\n"
	}
	lines := []string{}
	if display.Cause && decision.Cause != "" {
		lines = append(lines, "Cause: "+sanitizeTerminalText(decision.Cause))
	}
	if display.Consequence && decision.Consequence != "" {
		lines = append(lines, "Consequence: "+sanitizeTerminalText(decision.Consequence))
	}
	if display.Change {
		lines = append(lines, "Suggested command: "+sanitizeTerminalText(decision.Suggestion))
	}
	if display.Confidence {
		lines = append(lines, "Confidence level: "+confidencePresentation(decision.Confidence))
	}
	if display.Risk {
		lines = append(lines, "Risk level: "+string(decision.Risk))
		if decision.RiskRationale != "" {
			lines = append(lines, "Risk rationale: "+sanitizeTerminalText(decision.RiskRationale))
		}
	}
	if display.Trace && len(decision.Trace) > 0 {
		trace := make([]string, len(decision.Trace))
		for index, value := range decision.Trace {
			trace[index] = sanitizeTerminalText(value)
		}
		lines = append(lines, "Trace: "+strings.Join(trace, "; "))
	}
	if len(lines) == 0 {
		return ""
	}
	return strings.Join(lines, "\n") + "\n"
}

func diagnosticLabel(value, color string, enabled bool) string {
	if !enabled {
		return value
	}
	return "\x1b[" + color + "m" + value + "\x1b[0m"
}

func diagnosticColorEnabled(mode string, output io.Writer, environment func(string) string) (bool, error) {
	switch mode {
	case colorNever:
		return false, nil
	case colorAlways:
		return true, nil
	case colorAuto:
		if environment("NO_COLOR") != "" || environment("TERM") == "dumb" {
			return false, nil
		}
		file, ok := output.(*os.File)
		if !ok {
			return false, nil
		}
		info, err := file.Stat()
		if err != nil {
			return false, nil
		}
		return info.Mode()&os.ModeCharDevice != 0, nil
	default:
		return false, fmt.Errorf("--color must be auto, always, or never")
	}
}

func configCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 || args[0] == "show" {
		cfg, err := config.Load(config.Paths{Home: os.UserHomeDir, CWD: os.Getwd, Env: os.Getenv, Environ: os.Environ})
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(cfg))
	}
	if len(args) != 3 || args[0] != "set" {
		return clierr.New(clierr.Usage, "usage: close-enough config [show|set <key> <value>]")
	}
	path, err := config.GlobalPath(os.UserHomeDir)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	cfg, err := config.LoadGlobal(path)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	if err := cfg.Set(args[1], args[2]); err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	return clierr.Wrap(clierr.Configuration, config.Write(path, cfg))
}

func ruleCommand(args []string, stdout io.Writer) error {
	usage := "usage: close-enough rule <list|add <id> <command>|update <id> <command>|remove <id>>"
	if len(args) == 0 {
		return clierr.New(clierr.Usage, usage)
	}
	path, err := config.GlobalPath(os.UserHomeDir)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	cfg, err := config.LoadGlobal(path)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	switch args[0] {
	case "list":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough rule list")
		}
		exceptions := cfg.RuleExceptions
		if exceptions == nil {
			exceptions = []config.RuleException{}
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(exceptions))
	case "add", "update":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough rule "+args[0]+" <id> <command>")
		}
		if args[0] == "add" {
			err = cfg.AddRuleException(config.RuleException{ID: args[1], Command: args[2]})
		} else {
			err = cfg.UpdateRuleException(args[1], args[2])
		}
	case "remove":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough rule remove <id>")
		}
		err = cfg.RemoveRuleException(args[1])
	default:
		return clierr.New(clierr.Usage, usage)
	}
	if err != nil {
		return clierr.New(clierr.Usage, err.Error())
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	return clierr.Wrap(clierr.Configuration, config.Write(path, cfg))
}

func packCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "usage: close-enough pack <validate|install|uninstall> ...")
	}
	switch args[0] {
	case "validate":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough pack validate <path>")
		}
		pack, err := packs.Load(args[1])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		if _, err := packs.Compile(pack); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		_, err = fmt.Fprintln(stdout, "valid", pack.ID, pack.Version)
		return clierr.Wrap(clierr.Operation, err)
	case "install":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough pack install <path>")
		}
		directory, err := packDirectory(os.UserHomeDir, os.Getenv)
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		path, err := packs.Install(args[1], directory)
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		_, err = fmt.Fprintln(stdout, "installed", path)
		return clierr.Wrap(clierr.Operation, err)
	case "uninstall":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough pack uninstall <id> <version>")
		}
		directory, err := packDirectory(os.UserHomeDir, os.Getenv)
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		path, err := packs.Uninstall(directory, args[1], args[2])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		_, err = fmt.Fprintln(stdout, "uninstalled", path)
		return clierr.Wrap(clierr.Operation, err)
	default:
		return clierr.New(clierr.Usage, "usage: close-enough pack <validate|install|uninstall> ...")
	}
}

func packDirectory(home func() (string, error), environment func(string) string) (string, error) {
	base := environment("XDG_DATA_HOME")
	if base == "" || !filepath.IsAbs(base) {
		value, err := home()
		if err != nil {
			return "", err
		}
		base = filepath.Join(value, ".local", "share")
	}
	return filepath.Join(base, "close-enough", "packs"), nil
}

func doctorCommand(stdout io.Writer) error {
	result := shell.Doctor(os.Getenv("SHELL"), runtimeGOOS())
	return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(struct {
		shell.DoctorResult
		Runtime runtimecheck.Report `json:"runtime"`
	}{DoctorResult: result, Runtime: runtimecheck.Current()}))
}

func mustGetwd() string {
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return cwd
}

func runtimeGOOS() string { return strings.TrimSpace(runtimeOS()) }
