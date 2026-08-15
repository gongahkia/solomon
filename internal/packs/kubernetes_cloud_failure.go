package packs

import (
	"errors"
	"regexp"
	"sort"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

const maxKubernetesCloudFailureOutputBytes = 8 << 10

var ErrKubernetesCloudFailureOutputTooLarge = errors.New("kubernetes/cloud failure output exceeds size limit")

var kubernetesCloudFailurePatterns = []struct {
	kind    string
	pattern *regexp.Regexp
}{
	{"aws-template-path-invalid", regexp.MustCompile(`(?m)^Invalid template path ([^\r\n]+)$`)},
	{"helm-chart-path-missing", regexp.MustCompile(`(?m)^Error: INSTALLATION FAILED: path "([^"\r\n]+)" not found$`)},
	{"helm-unknown-subcommand", regexp.MustCompile(`(?m)^Error: unknown command "([^"\r\n]+)" for "helm"$`)},
	{"kubectl-path-missing", regexp.MustCompile(`(?m)^error: the path "([^"\r\n]+)" does not exist$`)},
	{"kubectl-unknown-subcommand", regexp.MustCompile(`(?m)^error: unknown command "([^"\r\n]+)" for "kubectl"$`)},
	{"terraform-varfile-missing", regexp.MustCompile(`(?m)^Given variables file ([^\r\n]+) does not exist\.$`)},
}

func ExtractKubernetesCloudFailureEvidence(output string) ([]diagnose.Evidence, error) {
	if len(output) > maxKubernetesCloudFailureOutputBytes {
		return nil, ErrKubernetesCloudFailureOutputTooLarge
	}
	unique := map[string]diagnose.Evidence{}
	for _, extractor := range kubernetesCloudFailurePatterns {
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
