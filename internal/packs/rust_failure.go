package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const maxRustFailureOutputBytes = 8 << 10

var ErrRustFailureOutputTooLarge = errors.New("Rust failure output exceeds size limit")

var rustFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"cargo-manifest-path-invalid", regexp.MustCompile("(?m)^error: the manifest-path must be a path to a Cargo\\.toml file: [`']?([^`'\\r\\n]+)[`']?$")},
	{"cargo-unknown-argument", regexp.MustCompile("(?m)^error: unexpected argument ['`]([^'`\\r\\n]+)['`] found$")},
	{"cargo-unknown-subcommand", regexp.MustCompile("(?m)^error: no such command: [`']([^`'\\r\\n]+)[`']$")},
	{"rustc-source-not-found", regexp.MustCompile("(?m)^error: couldn't read [`']([^`'\\r\\n]+)[`']:")},
	{"rustup-invalid-toolchain", regexp.MustCompile("(?m)^error: invalid value ['`]([^'`\\r\\n]+)['`] for ['`]\\[\\+toolchain\\]['`]:")},
}

func ExtractRustFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxRustFailureOutputBytes {
		return nil, ErrRustFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range rustFailurePatterns {
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
