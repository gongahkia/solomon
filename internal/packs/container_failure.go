package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const maxContainerFailureOutputBytes = 8 << 10

var ErrContainerFailureOutputTooLarge = errors.New("container failure output exceeds size limit")

var containerFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"container-file-not-found", regexp.MustCompile(`(?m)(?:^|: )open ([^\r\n]+): no such file or directory$`)},
	{"container-unknown-command", regexp.MustCompile(`(?m)^docker: unknown command: docker ([^\r\n ]+)$`)},
	{"container-unknown-flag", regexp.MustCompile(`(?m)^unknown flag: (--[^\r\n ]+)$`)},
}

func ExtractContainerFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxContainerFailureOutputBytes {
		return nil, ErrContainerFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range containerFailurePatterns {
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
