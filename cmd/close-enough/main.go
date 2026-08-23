package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/gongahkia/close-enough/internal/capture"
	"github.com/gongahkia/close-enough/internal/clierr"
	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/daemon"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/localstate"
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
		// #nosec G705 -- Errors are rendered for a terminal, not an HTML response.
		fmt.Fprint(os.Stderr, renderError(err))
		os.Exit(clierr.ExitOperation)
	}
	if err := run(args, os.Stdout, os.Stderr); err != nil {
		// #nosec G705 -- Errors are rendered for a terminal, not an HTML response.
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
		case unicode.IsControl(character) || unicode.Is(unicode.Bidi_Control, character):
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
	if args[0] == "--help" || args[0] == "-h" || args[0] == "help" {
		return helpCommand(args[1:], stdout)
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
	case "learn":
		return learnCommand(args[1:], stdout)
	case "pack":
		return packCommand(args[1:], stdout)
	case "daemon":
		return daemonCommand(args[1:], stdout)
	case "doctor":
		return doctorCommand(stdout)
	case "checksum":
		return checksumCommand(args[1:], stdout)
	case "capture":
		return captureCommand(args[1:], stdout)
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
	if _, err := fmt.Fprintln(w, "usage: close-enough <init|check|config|doctor|version|help>\n\nstart here:\n  close-enough init --shell zsh\n  close-enough check --format plain --command 'git sttaus'\n\ncommands:\n  init       print shell integration\n  check      inspect one command\n  config     view or change configuration\n  doctor     report adapter support\n  version    print build information\n  help       show this help\n\nadvanced: inspect-decision, rule, learn, pack, daemon, checksum"); err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	return clierr.New(clierr.Usage, "invalid command")
}

func helpCommand(args []string, stdout io.Writer) error {
	if len(args) > 1 {
		return clierr.New(clierr.Usage, "usage: close-enough help [init|check|config|doctor]")
	}
	if len(args) == 0 {
		_, err := fmt.Fprintln(stdout, "close-enough keeps shell repairs safe and quiet by default.\n\nusage: close-enough <init|check|config|doctor|version|help>\n\nstart here:\n  close-enough init --shell zsh\n  close-enough check --format plain --command 'git sttaus'\n\ncommands:\n  init       print shell integration\n  check      inspect one command\n  config     view or change configuration\n  doctor     report adapter support\n  version    print build information\n  help       show this help\n\nadvanced: inspect-decision, rule, learn, pack, daemon, checksum")
		return clierr.Wrap(clierr.Operation, err)
	}
	var text string
	switch args[0] {
	case "init":
		text = "usage: close-enough init --shell <bash|zsh|fish|powershell> [--experimental-output-capture]\n\nPrint shell integration. Experimental output capture is opt-in and currently available for Bash and Zsh."
	case "check":
		text = "usage: close-enough check --command <command> [--stage pre|post] [--format json|plain|record] [--color auto|always|never]"
	case "config":
		text = "usage: close-enough config [show|set <key> <value>]"
	case "doctor":
		text = "usage: close-enough doctor\n\nReport capabilities and limitations for the current shell."
	default:
		return clierr.New(clierr.Usage, "usage: close-enough help [init|check|config|doctor]")
	}
	_, err := fmt.Fprintln(stdout, text)
	return clierr.Wrap(clierr.Operation, err)
}

func learnCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "usage: close-enough learn <list|activate|edit|set-action|enable|disable|remove|purge> ...")
	}
	cfg, err := config.Load(config.Paths{Home: os.UserHomeDir, CWD: os.Getwd, Env: os.Getenv, Environ: os.Environ})
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	if !cfg.LocalLearningEnabled {
		return clierr.New(clierr.Configuration, "local learning is disabled")
	}
	directory, err := daemon.StateDirectory(os.UserHomeDir, os.Getenv)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	store, err := localstate.Open(directory)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	defer store.Close()
	switch args[0] {
	case "list":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough learn list")
		}
		drafts, err := store.ListReviewableDrafts(context.Background())
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		rules, err := store.ListActiveRules(context.Background())
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(struct {
			Drafts []localstate.Draft       `json:"drafts"`
			Rules  []localstate.LearnedRule `json:"rules"`
		}{Drafts: drafts, Rules: rules}))
	case "activate":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough learn activate <draft-id> <off|hint|rewrite>")
		}
		id, err := strconv.ParseInt(args[1], 10, 64)
		if err != nil {
			return clierr.New(clierr.Usage, "learned rule draft id must be an integer")
		}
		rule, err := store.ActivateDraft(context.Background(), id, args[2])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(rule))
	case "edit":
		if len(args) != 4 {
			return clierr.New(clierr.Usage, "usage: close-enough learn edit <draft-id> <failed-command> <corrected-command>")
		}
		id, err := strconv.ParseInt(args[1], 10, 64)
		if err != nil {
			return clierr.New(clierr.Usage, "learned rule draft id must be an integer")
		}
		draft, err := store.UpdateDraft(context.Background(), id, args[2], args[3])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(draft))
	case "set-action":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough learn set-action <rule-id> <off|hint|rewrite>")
		}
		id, err := strconv.ParseInt(args[1], 10, 64)
		if err != nil {
			return clierr.New(clierr.Usage, "learned rule id must be an integer")
		}
		if err := store.SetRuleAction(context.Background(), id, args[2]); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		return nil
	case "enable", "disable":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough learn "+args[0]+" <rule-id>")
		}
		id, err := strconv.ParseInt(args[1], 10, 64)
		if err != nil {
			return clierr.New(clierr.Usage, "learned rule id must be an integer")
		}
		if err := store.SetRuleEnabled(context.Background(), id, args[0] == "enable"); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		return nil
	case "remove":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough learn remove <rule-id>")
		}
		id, err := strconv.ParseInt(args[1], 10, 64)
		if err != nil {
			return clierr.New(clierr.Usage, "learned rule id must be an integer")
		}
		if err := store.DeleteRule(context.Background(), id); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		return nil
	case "purge":
		if len(args) != 2 || args[1] != "--confirm=PURGE" {
			return clierr.New(clierr.Usage, "usage: close-enough learn purge --confirm=PURGE")
		}
		if err := store.PurgeLearning(context.Background()); err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		restartDaemonIfRunning()
		return nil
	default:
		return clierr.New(clierr.Usage, "usage: close-enough learn <list|activate|edit|set-action|enable|disable|remove|purge> ...")
	}
}

func restartDaemonIfRunning() {
	directory, err := daemon.RuntimeDirectory(os.UserHomeDir, os.Getenv)
	if err != nil {
		return
	}
	endpoint, err := daemon.LocalEndpoint(directory)
	if err != nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Millisecond)
	defer cancel()
	_, _ = (daemon.Client{Endpoint: endpoint, Timeout: 15 * time.Millisecond}).Request(ctx, daemon.Request{Version: daemon.ProtocolVersion, Operation: daemon.StopOperation})
}

func daemonCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "usage: close-enough daemon <serve|status|stop|request>")
	}
	runtimeDirectory, err := daemon.RuntimeDirectory(os.UserHomeDir, os.Getenv)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	endpoint, err := daemon.LocalEndpoint(runtimeDirectory)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	switch args[0] {
	case "status":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough daemon status")
		}
		response, err := (daemon.Client{Endpoint: endpoint}).Request(context.Background(), daemon.Request{Version: daemon.ProtocolVersion, Operation: daemon.StatusOperation})
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(response))
	case "serve":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough daemon serve")
		}
		cfg, err := config.Load(config.Paths{Home: os.UserHomeDir, CWD: os.Getwd, Env: os.Getenv, Environ: os.Environ})
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		resolver, err := runtimePackResolver(cfg, os.UserHomeDir, os.Getenv)
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		var store *localstate.Store
		var learnedRules []localstate.LearnedRule
		if cfg.LocalLearningEnabled {
			stateDirectory, err := daemon.StateDirectory(os.UserHomeDir, os.Getenv)
			if err != nil {
				return clierr.Wrap(clierr.Configuration, err)
			}
			store, err = localstate.Open(stateDirectory)
			if err != nil {
				return clierr.Wrap(clierr.Configuration, err)
			}
			defer store.Close()
			if _, err := store.DeleteObservationsBefore(context.Background(), time.Now().AddDate(0, 0, -cfg.LearningRetentionDays)); err != nil {
				return clierr.Wrap(clierr.Configuration, err)
			}
			learnedRules, err = store.ListActiveRules(context.Background())
			if err != nil {
				return clierr.Wrap(clierr.Configuration, err)
			}
		}
		service := daemon.Service{Engine: diagnose.New(diagnose.Options{Config: cfg, Path: os.Getenv("PATH"), CWD: mustGetwd(), SemanticResolver: resolver}), Config: cfg, Packs: resolver, Store: store, LearnedRules: learnedRules}
		server, err := daemon.NewServer(endpoint, service.Handle)
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		if err := server.Listen(); err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
		defer stop()
		return clierr.Wrap(clierr.Operation, server.Serve(ctx))
	case "stop":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough daemon stop")
		}
		response, err := (daemon.Client{Endpoint: endpoint}).Request(context.Background(), daemon.Request{Version: daemon.ProtocolVersion, Operation: daemon.StopOperation})
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(response))
	case "request":
		return daemonRequestCommand(args[1:], endpoint, stdout)
	default:
		return clierr.New(clierr.Usage, "usage: close-enough daemon <serve|status|stop|request>")
	}
}

func daemonRequestCommand(args []string, endpoint daemon.Endpoint, stdout io.Writer) error {
	fs := flag.NewFlagSet("daemon request", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	operation := fs.String("operation", "", "daemon operation")
	shellName := fs.String("shell", "", "shell")
	command := fs.String("command", "", "command line")
	failureOutput := fs.String("failure-output", "", "failure output")
	session := fs.String("session", "", "shell session")
	token := fs.String("token", "", "confirmation, undo, or failure token")
	format := fs.String("format", "json", "json, record, or undo-record")
	ensure := fs.Bool("ensure", true, "start the local daemon when unavailable")
	if err := fs.Parse(args); err != nil || *operation == "" || fs.NArg() != 0 {
		return clierr.New(clierr.Usage, "usage: close-enough daemon request --operation <handshake|status|pre-send|post-failure|post-success|undo|confirm|stop> [--shell <shell>] [--command <command>] [--failure-output <output>] [--session <id>] [--token <token>] [--format <json|record|undo-record>] [--ensure=<true|false>]")
	}
	if *format != "json" && *format != "record" && *format != "undo-record" {
		return clierr.New(clierr.Usage, "daemon request --format must be json, record, or undo-record")
	}
	request := daemon.Request{
		Version:       daemon.ProtocolVersion,
		Operation:     daemon.Operation(*operation),
		Shell:         *shellName,
		Command:       *command,
		FailureOutput: *failureOutput,
		Session:       *session,
		Token:         *token,
	}
	response, err := requestDaemon(context.Background(), endpoint, request, *ensure)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	if *format == "record" {
		_, err := io.WriteString(stdout, daemonRecord(response))
		return clierr.Wrap(clierr.Operation, err)
	}
	if *format == "undo-record" {
		_, err := io.WriteString(stdout, daemonUndoRecord(response))
		return clierr.Wrap(clierr.Operation, err)
	}
	return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(response))
}

func daemonRecord(response daemon.Response) string {
	return daemonRecordWithUndo(response, false)
}

func daemonUndoRecord(response daemon.Response) string {
	return daemonRecordWithUndo(response, true)
}

func daemonRecordWithUndo(response daemon.Response, includeUndoToken bool) string {
	var evidence []byte
	if len(response.Evidence) > 0 {
		evidence, _ = json.Marshal(response.Evidence)
	}
	fields := []string{
		strconv.Itoa(response.Version),
		response.Action,
		response.Risk,
		response.Confidence,
		base64.RawStdEncoding.EncodeToString([]byte(response.Explanation)),
		base64.RawStdEncoding.EncodeToString(evidence),
		base64.RawStdEncoding.EncodeToString([]byte(response.Suggestion)),
	}
	if includeUndoToken {
		fields = append(fields, base64.RawStdEncoding.EncodeToString([]byte(response.UndoToken)))
	}
	return strings.Join(fields, "\t") + "\n"
}

var startDaemonProcess = startDaemonProcessDefault
var daemonStartMu sync.Mutex

func requestDaemon(parent context.Context, endpoint daemon.Endpoint, request daemon.Request, ensure bool) (daemon.Response, error) {
	ctx, cancel := context.WithTimeout(parent, 95*time.Millisecond)
	defer cancel()
	client := daemon.Client{Endpoint: endpoint, Timeout: 15 * time.Millisecond}
	response, err := client.Request(ctx, request)
	if err == nil || !ensure || !errors.Is(err, daemon.ErrUnavailable) {
		return response, err
	}
	daemonStartMu.Lock()
	defer daemonStartMu.Unlock()
	response, err = client.Request(ctx, request)
	if err == nil || !errors.Is(err, daemon.ErrUnavailable) {
		return response, err
	}
	if err := startDaemonProcess(); err != nil {
		return daemon.Response{}, errors.Join(daemon.ErrUnavailable, err)
	}
	for {
		response, err = client.Request(ctx, request)
		if err == nil || !errors.Is(err, daemon.ErrUnavailable) || ctx.Err() != nil {
			return response, err
		}
		select {
		case <-ctx.Done():
			return daemon.Response{}, errors.Join(daemon.ErrUnavailable, ctx.Err())
		case <-time.After(10 * time.Millisecond):
		}
	}
}

func startDaemonProcessDefault() error {
	path, err := os.Executable()
	if err != nil {
		return err
	}
	// #nosec G204 -- os.Executable returns this already-running binary, not shell input.
	command := exec.Command(path, "daemon", "serve")
	detachDaemonProcess(command)
	if err := command.Start(); err != nil {
		return err
	}
	return command.Process.Release()
}

func checksumCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "checksum requires generate or verify")
	}
	switch args[0] {
	case "generate":
		fs := flag.NewFlagSet("checksum generate", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		file := fs.String("file", "", "artifact file")
		if err := fs.Parse(args[1:]); err != nil || *file == "" || fs.NArg() != 0 {
			return clierr.New(clierr.Usage, "checksum generate requires --file")
		}
		digest, name, err := checksumFile(*file)
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		_, err = fmt.Fprintf(stdout, "%s  %s\n", digest, name)
		return clierr.Wrap(clierr.Operation, err)
	case "verify":
		fs := flag.NewFlagSet("checksum verify", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		file := fs.String("file", "", "artifact file")
		manifest := fs.String("manifest", "", "checksum manifest")
		if err := fs.Parse(args[1:]); err != nil || *file == "" || *manifest == "" || fs.NArg() != 0 {
			return clierr.New(clierr.Usage, "checksum verify requires --file and --manifest")
		}
		if err := verifyChecksumFile(*file, *manifest); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		return nil
	default:
		return clierr.New(clierr.Usage, "checksum requires generate or verify")
	}
}

func checksumFile(path string) (string, string, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", "", err
	}
	if !info.Mode().IsRegular() {
		return "", "", fmt.Errorf("checksum file is not a regular file")
	}
	// #nosec G304 -- checksum deliberately reads the explicit local --file argument.
	file, err := os.Open(path)
	if err != nil {
		return "", "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), filepath.Base(path), nil
}

func verifyChecksumFile(path, manifestPath string) error {
	digest, name, err := checksumFile(path)
	if err != nil {
		return err
	}
	// #nosec G304 -- checksum deliberately reads the explicit local --manifest argument.
	manifest, err := os.ReadFile(manifestPath)
	if err != nil {
		return err
	}
	const maxManifestBytes = 1 << 20
	if len(manifest) > maxManifestBytes {
		return fmt.Errorf("checksum manifest exceeds size limit")
	}
	expected := ""
	for index, line := range strings.Split(string(manifest), "\n") {
		if line == "" && index == len(strings.Split(string(manifest), "\n"))-1 {
			continue
		}
		if strings.ContainsRune(line, '\r') {
			return fmt.Errorf("checksum manifest contains carriage return")
		}
		candidate, artifact, ok := strings.Cut(line, "  ")
		if !ok || artifact == "" || filepath.Base(artifact) != artifact {
			return fmt.Errorf("checksum manifest has invalid entry")
		}
		decoded, err := hex.DecodeString(candidate)
		if err != nil || len(decoded) != sha256.Size || hex.EncodeToString(decoded) != candidate {
			return fmt.Errorf("checksum manifest has invalid digest")
		}
		if artifact != name {
			continue
		}
		if expected != "" {
			return fmt.Errorf("checksum manifest has duplicate artifact")
		}
		expected = candidate
	}
	if expected == "" {
		return fmt.Errorf("checksum manifest does not contain %q", name)
	}
	if digest != expected {
		return fmt.Errorf("checksum mismatch for %q", name)
	}
	return nil
}

func initCommand(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("init", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	shellName := fs.String("shell", "", "shell")
	experimentalOutputCapture := fs.Bool("experimental-output-capture", false, "enable experimental output capture")
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
	if *experimentalOutputCapture {
		bootstrap, err := shell.ExperimentalCaptureBootstrap(*shellName)
		if err != nil {
			return clierr.Wrap(clierr.Usage, err)
		}
		script = bootstrap + "\n" + script
	}
	_, err = io.WriteString(stdout, script)
	return clierr.Wrap(clierr.Operation, err)
}

func captureCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "usage: close-enough capture <start|read|reset>")
	}
	switch args[0] {
	case "start":
		return captureStartCommand(args[1:])
	case "read":
		fs := flag.NewFlagSet("capture read", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		socket := fs.String("socket", "", "relay socket")
		command := fs.String("command", "", "command line")
		if err := fs.Parse(args[1:]); err != nil || *socket == "" || fs.NArg() != 0 {
			return clierr.New(clierr.Usage, "usage: close-enough capture read --socket <socket> --command <command>")
		}
		output, err := capture.Read(*socket, *command)
		if err != nil {
			return clierr.Wrap(clierr.Operation, err)
		}
		_, err = io.WriteString(stdout, output)
		return clierr.Wrap(clierr.Operation, err)
	case "reset":
		fs := flag.NewFlagSet("capture reset", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		socket := fs.String("socket", "", "relay socket")
		if err := fs.Parse(args[1:]); err != nil || *socket == "" || fs.NArg() != 0 {
			return clierr.New(clierr.Usage, "usage: close-enough capture reset --socket <socket>")
		}
		return clierr.Wrap(clierr.Operation, capture.Reset(*socket))
	default:
		return clierr.New(clierr.Usage, "usage: close-enough capture <start|read|reset>")
	}
}

func captureStartCommand(args []string) error {
	fs := flag.NewFlagSet("capture start", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	shellName := fs.String("shell", "", "shell")
	if err := fs.Parse(args); err != nil || fs.NArg() != 0 || (*shellName != "bash" && *shellName != "zsh") {
		return clierr.New(clierr.Usage, "usage: close-enough capture start --shell <bash|zsh>")
	}
	if runtime.GOOS == "windows" {
		return clierr.New(clierr.Operation, "experimental output capture is unavailable on Windows")
	}
	scriptPath, err := exec.LookPath("script")
	if err != nil {
		return clierr.Wrap(clierr.Operation, errors.New("experimental output capture requires the script utility"))
	}
	if _, err := exec.LookPath("mkfifo"); err != nil {
		return clierr.Wrap(clierr.Operation, errors.New("experimental output capture requires mkfifo"))
	}
	directory, err := os.MkdirTemp("", "close-enough-capture-*")
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	defer os.RemoveAll(directory)
	fifo := filepath.Join(directory, "output")
	if err := exec.Command("mkfifo", "-m", "600", fifo).Run(); err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	token, err := randomCaptureToken()
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	relay, err := capture.Start(filepath.Join(directory, "relay.sock"), token)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	defer relay.Close()
	go func() {
		reader, err := os.Open(fifo)
		if err == nil {
			defer reader.Close()
			_ = relay.FeedReader(reader)
		}
	}()
	shellPath, err := exec.LookPath(*shellName)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	command := scriptCaptureCommand(scriptPath, fifo, shellPath)
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, os.Stdout, os.Stderr
	command.Env = append(os.Environ(), "CLOSE_ENOUGH_CAPTURE_ACTIVE=1", "CLOSE_ENOUGH_CAPTURE_SOCKET="+filepath.Join(directory, "relay.sock"), "CLOSE_ENOUGH_CAPTURE_MARKER="+token)
	return clierr.Wrap(clierr.Operation, command.Run())
}

func scriptCaptureCommand(scriptPath, fifo, shellPath string) *exec.Cmd {
	if runtime.GOOS == "linux" {
		return exec.Command(scriptPath, "-q", "-f", fifo, "-c", "exec "+quotePOSIX(shellPath)+" -i")
	}
	return exec.Command(scriptPath, "-q", fifo, shellPath, "-i")
}

func quotePOSIX(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\\\"'\\\"'") + "'"
}

func randomCaptureToken() (string, error) {
	data := make([]byte, 16)
	if _, err := rand.Read(data); err != nil {
		return "", err
	}
	return hex.EncodeToString(data), nil
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
	engine, err := bundledDiagnosticEngine(cfg)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	decision, err := engine.Check(*command, *stage)
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
		// #nosec G705 -- The diagnostic is terminal output, not an HTML response.
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

func bundledDiagnosticEngine(cfg config.Config) (diagnose.Engine, error) {
	resolver, err := runtimePackResolver(cfg, os.UserHomeDir, os.Getenv)
	if err != nil {
		return diagnose.Engine{}, err
	}
	return diagnose.New(diagnose.Options{Config: cfg, Path: os.Getenv("PATH"), CWD: mustGetwd(), SemanticResolver: resolver}), nil
}

func runtimePackResolver(cfg config.Config, home func() (string, error), environment func(string) string) (packs.RuntimeResolver, error) {
	if !cfg.CuratedPacksEnabled {
		return packs.RuntimeResolver{}, nil
	}
	bundled, err := packs.LoadBundled()
	if err != nil {
		return packs.RuntimeResolver{}, err
	}
	directory, err := packDirectory(home, environment)
	if err != nil {
		return packs.RuntimeResolver{}, err
	}
	keyringPath, err := packKeyringPath(home, environment)
	if err != nil {
		return packs.RuntimeResolver{}, err
	}
	keyring, err := packs.LoadKeyring(keyringPath)
	if err != nil {
		return packs.RuntimeResolver{}, err
	}
	installed, err := packs.LoadInstalledVerified(directory, keyring)
	if err != nil {
		return packs.RuntimeResolver{}, err
	}
	return packs.NewRuntimeResolverWithInstalled(bundled, installed)
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
	engine, err := bundledDiagnosticEngine(cfg)
	if err != nil {
		return clierr.Wrap(clierr.Operation, err)
	}
	decision, err := engine.Check(*command, *stage)
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
		return clierr.New(clierr.Usage, "usage: close-enough pack <validate|install|uninstall|trust> ...")
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
		// #nosec G705 -- Pack metadata is printed to a terminal, not an HTML response.
		_, err = fmt.Fprintln(stdout, "valid", pack.ID, pack.Version)
		return clierr.Wrap(clierr.Operation, err)
	case "install":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough pack install <pack.json> <signature>")
		}
		directory, err := packDirectory(os.UserHomeDir, os.Getenv)
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		keyringPath, err := packKeyringPath(os.UserHomeDir, os.Getenv)
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		keyring, err := packs.LoadKeyring(keyringPath)
		if err != nil {
			return clierr.Wrap(clierr.Configuration, err)
		}
		// #nosec G304,G703 -- pack install deliberately reads the explicit local pack argument.
		payload, err := os.ReadFile(args[1])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		// #nosec G304,G703 -- pack install deliberately reads the explicit local signature argument.
		signature, err := os.ReadFile(args[2])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		path, err := packs.InstallVerified(payload, signature, directory, keyring)
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		restartDaemonIfRunning()
		// #nosec G705 -- The managed filesystem path is printed to a terminal, not an HTML response.
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
		restartDaemonIfRunning()
		// #nosec G705 -- The managed filesystem path is printed to a terminal, not an HTML response.
		_, err = fmt.Fprintln(stdout, "uninstalled", path)
		return clierr.Wrap(clierr.Operation, err)
	case "trust":
		return packTrustCommand(args[1:], stdout)
	default:
		return clierr.New(clierr.Usage, "usage: close-enough pack <validate|install|uninstall|trust> ...")
	}
}

func packTrustCommand(args []string, stdout io.Writer) error {
	if len(args) == 0 {
		return clierr.New(clierr.Usage, "usage: close-enough pack trust <add|list|remove> ...")
	}
	path, err := packKeyringPath(os.UserHomeDir, os.Getenv)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	keyring, err := packs.LoadKeyring(path)
	if err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	switch args[0] {
	case "list":
		if len(args) != 1 {
			return clierr.New(clierr.Usage, "usage: close-enough pack trust list")
		}
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(keyring))
	case "add":
		if len(args) != 3 {
			return clierr.New(clierr.Usage, "usage: close-enough pack trust add <publisher> <base64-ed25519-public-key>")
		}
		key, err := packs.ParsePublisherPublicKey(args[2])
		if err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
		if err := keyring.Add(args[1], key); err != nil {
			return clierr.Wrap(clierr.Input, err)
		}
	case "remove":
		if len(args) != 2 {
			return clierr.New(clierr.Usage, "usage: close-enough pack trust remove <publisher>")
		}
		if !keyring.Remove(args[1]) {
			return clierr.New(clierr.Input, "publisher is not trusted")
		}
	default:
		return clierr.New(clierr.Usage, "usage: close-enough pack trust <add|list|remove> ...")
	}
	if err := packs.WriteKeyring(path, keyring); err != nil {
		return clierr.Wrap(clierr.Configuration, err)
	}
	restartDaemonIfRunning()
	return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(keyring))
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

func packKeyringPath(home func() (string, error), environment func(string) string) (string, error) {
	base := environment("XDG_CONFIG_HOME")
	if base == "" || !filepath.IsAbs(base) {
		value, err := home()
		if err != nil {
			return "", err
		}
		base = filepath.Join(value, ".config")
	}
	return filepath.Join(base, "close-enough", "pack-keyring.json"), nil
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
