package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const maxJavaScriptFailureOutputBytes = 8 << 10

var ErrJavaScriptFailureOutputTooLarge = errors.New("JavaScript failure output exceeds size limit")

var javaScriptFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"bun-unresolved-module", regexp.MustCompile(`(?m)^error: Could not resolve: "([^"\r\n]+)"`)},
	{"deno-module-not-found", regexp.MustCompile(`(?m)^error: Module not found "([^"\r\n]+)"`)},
	{"node-module-not-found", regexp.MustCompile(`(?m)^Error(?: \[[A-Z0-9_]+\])?: Cannot find module ['"]([^'"]+)['"]`)},
	{"node-unknown-option", regexp.MustCompile(`(?m)^node: (?:bad option|unknown option): ([^\r\n ]+)`)},
}

func ExtractJavaScriptFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxJavaScriptFailureOutputBytes {
		return nil, ErrJavaScriptFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range javaScriptFailurePatterns {
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
