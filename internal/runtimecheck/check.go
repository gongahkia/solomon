package runtimecheck

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

type Finding struct {
	Code string `json:"code"`
}

type Report struct {
	Safe     bool      `json:"safe"`
	Findings []Finding `json:"findings,omitempty"`
}

type Options struct {
	Path             string
	EffectiveUserID  int
	WorkingDirectory os.FileMode
	WorkingDirError  error
}

func Current() Report {
	directory, err := os.Getwd()
	if err != nil {
		return Check(Options{Path: os.Getenv("PATH"), EffectiveUserID: os.Geteuid(), WorkingDirError: err})
	}
	info, err := os.Stat(directory)
	if err != nil {
		return Check(Options{Path: os.Getenv("PATH"), EffectiveUserID: os.Geteuid(), WorkingDirError: err})
	}
	return Check(Options{Path: os.Getenv("PATH"), EffectiveUserID: os.Geteuid(), WorkingDirectory: info.Mode()})
}

func Check(options Options) Report {
	findings := []Finding{}
	if options.EffectiveUserID == 0 {
		findings = append(findings, Finding{Code: "privileged-user"})
	}
	for _, directory := range filepath.SplitList(options.Path) {
		if directory == "" || !filepath.IsAbs(directory) {
			findings = append(findings, Finding{Code: "unsafe-path"})
			break
		}
	}
	if options.WorkingDirError != nil {
		findings = append(findings, Finding{Code: "working-directory-unavailable"})
	} else if options.WorkingDirectory.Perm()&0o022 != 0 {
		findings = append(findings, Finding{Code: "writable-working-directory"})
	}
	return Report{Safe: len(findings) == 0, Findings: findings}
}

func (report Report) Error() error {
	if report.Safe {
		return nil
	}
	codes := make([]string, len(report.Findings))
	for index, finding := range report.Findings {
		codes[index] = finding.Code
	}
	return errors.New("unsafe local runtime: " + strings.Join(codes, ","))
}
