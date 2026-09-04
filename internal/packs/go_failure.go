package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/solomon/internal/diagnose"
)

const maxGoFailureOutputBytes = 8 << 10

var ErrGoFailureOutputTooLarge = errors.New("go failure output exceeds size limit")

var goFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"go-flag-unknown", regexp.MustCompile(`(?m)^flag provided but not defined: (-[^\r\n ]+)$`)},
	{"go-modfile-missing", regexp.MustCompile(`(?m)^go: open ([^\r\n]+): no such file or directory$`)},
	{"go-path-missing", regexp.MustCompile(`(?m)^(?:l)?stat ([^\r\n]+): (?:no such file or directory|directory not found)$`)},
	{"go-unknown-subcommand", regexp.MustCompile(`(?m)^go ([^\r\n :]+): unknown command$`)},
}

func ExtractGoFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxGoFailureOutputBytes {
		return nil, ErrGoFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range goFailurePatterns {
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
