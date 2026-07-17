package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const maxPythonFailureOutputBytes = 8 << 10

var ErrPythonFailureOutputTooLarge = errors.New("Python failure output exceeds size limit")

var pythonFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"pip-package-not-found", regexp.MustCompile(`(?m)^ERROR: Could not find a version that satisfies the requirement ([^\r\n ]+)`)},
	{"pytest-unknown-argument", regexp.MustCompile(`(?m)^.*pytest: error: unrecognized arguments: ([^\r\n ]+)`)},
	{"python-module-not-found", regexp.MustCompile(`(?m)^ModuleNotFoundError: No module named ['"]([^'"]+)['"]`)},
	{"python-path-not-found", regexp.MustCompile(`(?m)^FileNotFoundError: \[Errno 2\] No such file or directory: ['"]([^'"]+)['"]`)},
}

func ExtractPythonFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxPythonFailureOutputBytes {
		return nil, ErrPythonFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range pythonFailurePatterns {
		for _, match := range extractor.pattern.FindAllStringSubmatch(output, -1) {
			value := sanitizeFailureEvidence(match[1])
			if value != "" {
				unique[extractor.kind+"\x00"+value] = diagnose.Evidence{Kind: extractor.kind, Value: value}
			}
		}
	}
	evidence := make([]diagnose.Evidence, 0, len(unique))
	for _, value := range unique {
		evidence = append(evidence, value)
	}
	sort.Slice(evidence, func(left, right int) bool {
		if evidence[left].Kind != evidence[right].Kind {
			return evidence[left].Kind < evidence[right].Kind
		}
		return evidence[left].Value < evidence[right].Value
	})
	return evidence, nil
}
