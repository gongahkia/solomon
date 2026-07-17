package packs

import (
	"errors"
	"regexp"
	"sort"
	"strings"
	"unicode"

	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/redact"
)

const (
	maxGitFailureOutputBytes  = 8 << 10
	maxGitFailureEvidenceSize = 256
)

var ErrGitFailureOutputTooLarge = errors.New("Git failure output exceeds size limit")

var gitFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"git-pathspec-miss", regexp.MustCompile(`(?m)^(?:fatal: |error: )?pathspec '([^'\r\n]+)' did not match any file(?:\(s\)|s)?(?: known to git)?`)},
	{"git-unknown-option", regexp.MustCompile("(?m)^(?:error: )?unknown (?:option|switch) ['`]?([^'`\\r\\n ]+)")},
	{"git-unknown-subcommand", regexp.MustCompile(`(?m)^git: '([^'\r\n]+)' is not a git command`)},
}

func ExtractGitFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxGitFailureOutputBytes {
		return nil, ErrGitFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range gitFailurePatterns {
		for _, match := range extractor.pattern.FindAllStringSubmatch(output, -1) {
			value := sanitizeFailureEvidence(match[1])
			if value == "" {
				continue
			}
			unique[extractor.kind+"\x00"+value] = diagnose.Evidence{Kind: extractor.kind, Value: value}
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

func sanitizeFailureEvidence(value string) string {
	value = strings.TrimSpace(value)
	value, _ = redact.Text(value)
	if value == "" || len(value) > maxGitFailureEvidenceSize {
		return ""
	}
	for _, character := range value {
		if unicode.IsControl(character) {
			return ""
		}
	}
	return value
}
