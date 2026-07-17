package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/gongahkia/close-enough/internal/clierr"
	"github.com/gongahkia/close-enough/internal/config"
	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/packs"
	"github.com/gongahkia/close-enough/internal/shell"
)

var version = "dev"
var commit = "unknown"

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "close-enough:", err)
		os.Exit(clierr.Code(err))
	}
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
	case "config":
		return configCommand(args[1:], stdout)
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
	if _, err := fmt.Fprintln(w, "usage: close-enough <init|check|config|pack|doctor|version>"); err != nil {
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
	switch *format {
	case "json":
		return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(decision))
	case "plain":
		if decision.Suggestion == "" {
			_, err = fmt.Fprintln(stdout, "no suggestion")
			return clierr.Wrap(clierr.Operation, err)
		}
		_, err = fmt.Fprintf(stdout, "%s: %s\nDid you mean: %s\nRisk: %s\n", decision.Cause, decision.Consequence, decision.Suggestion, decision.Risk)
		return clierr.Wrap(clierr.Operation, err)
	case "record":
		_, err = fmt.Fprint(stdout, decision.Record())
		return clierr.Wrap(clierr.Operation, err)
	default:
		return clierr.New(clierr.Usage, "--format must be json, plain, or record")
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

func packCommand(args []string, stdout io.Writer) error {
	if len(args) != 2 || args[0] != "validate" {
		return clierr.New(clierr.Usage, "usage: close-enough pack validate <path>")
	}
	pack, err := packs.Load(args[1])
	if err != nil {
		return clierr.Wrap(clierr.Input, err)
	}
	if err := pack.Validate(); err != nil {
		return clierr.Wrap(clierr.Input, err)
	}
	_, err = fmt.Fprintln(stdout, "valid", pack.ID, pack.Version)
	return clierr.Wrap(clierr.Operation, err)
}

func doctorCommand(stdout io.Writer) error {
	result := shell.Doctor(os.Getenv("SHELL"), runtimeGOOS())
	return clierr.Wrap(clierr.Operation, json.NewEncoder(stdout).Encode(result))
}

func mustGetwd() string {
	cwd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return cwd
}

func runtimeGOOS() string { return strings.TrimSpace(runtimeOS()) }
