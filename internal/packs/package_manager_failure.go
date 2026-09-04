package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/solomon/internal/diagnose"
)

const maxPackageManagerFailureOutputBytes = 8 << 10

var ErrPackageManagerFailureOutputTooLarge = errors.New("package manager failure output exceeds size limit")

var packageManagerFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"brew-missing-formula", regexp.MustCompile(`(?m)^Error: No available formula with the name "([^"\r\n]+)"\.`)},
	{"npm-error-code", regexp.MustCompile(`(?m)^npm error code ([A-Z0-9_]+)$`)},
	{"npm-missing-script", regexp.MustCompile(`(?m)^npm error Missing script: "([^"\r\n]+)"$`)},
	{"pnpm-error-code", regexp.MustCompile(`(?m)^(ERR_PNPM_[A-Z0-9_]+)`)},
	{"yarn-unknown-command", regexp.MustCompile(`(?m)^error Command "([^"\r\n]+)" not found\.$`)},
}

func ExtractPackageManagerFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxPackageManagerFailureOutputBytes {
		return nil, ErrPackageManagerFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range packageManagerFailurePatterns {
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
