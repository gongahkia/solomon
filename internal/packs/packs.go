package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"unicode"
	"unicode/utf8"

	"github.com/gongahkia/close-enough/internal/diagnose"
	"github.com/gongahkia/close-enough/internal/securetemp"
)

type Pack struct {
	SchemaVersion    int      `json:"schema_version"`
	ID               string   `json:"id"`
	Version          string   `json:"version"`
	Publisher        string   `json:"publisher"`
	MinEngineVersion string   `json:"min_engine_version,omitempty"`
	Capabilities     []string `json:"capabilities,omitempty"`
	Rules            []Rule   `json:"rules"`
}

type Rule struct {
	ID            string        `json:"id"`
	Command       string        `json:"command"`
	Pattern       string        `json:"pattern"`
	Replacement   string        `json:"replacement"`
	Cause         string        `json:"cause"`
	Risk          diagnose.Risk `json:"risk"`
	RiskRationale string        `json:"risk_rationale"`
}

func Load(path string) (Pack, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Pack{}, err
	}
	return decodePack(data)
}

func decodePack(data []byte) (Pack, error) {
	var pack Pack
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&pack); err != nil {
		return Pack{}, fmt.Errorf("parse pack: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return Pack{}, errors.New("parse pack: multiple JSON values")
		}
		return Pack{}, fmt.Errorf("parse pack: trailing data: %w", err)
	}
	return pack, nil
}

func Install(source, directory string) (string, error) {
	data, err := os.ReadFile(source)
	if err != nil {
		return "", err
	}
	pack, err := decodePack(data)
	if err != nil {
		return "", err
	}
	if _, err := Compile(pack); err != nil {
		return "", err
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return "", err
	}
	target := filepath.Join(directory, pack.ID+"-"+pack.Version+".json")
	if _, err := os.Lstat(target); err == nil {
		return "", fmt.Errorf("pack %q is already installed", pack.ID)
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	temporary, err := securetemp.Create(directory, "."+filepath.Base(target)+".tmp-*")
	if err != nil {
		return "", err
	}
	defer temporary.Cleanup()
	if _, err := temporary.Write(data); err != nil {
		return "", err
	}
	if err := temporary.Commit(target); err != nil {
		return "", err
	}
	return target, nil
}

func (p Pack) Validate() error {
	if err := ValidateSchemaCompatibility(p.SchemaVersion); err != nil {
		return err
	}
	if !identifier(p.ID) || !semanticVersion(p.Version) || !identifier(p.Publisher) {
		return errors.New("id and publisher must be lowercase kebab identifiers; version must be semantic")
	}
	if err := validateCompatibilityMetadata(p); err != nil {
		return err
	}
	if len(p.Rules) == 0 {
		return errors.New("pack must contain at least one rule")
	}
	seen := map[string]struct{}{}
	for _, rule := range p.Rules {
		if !identifier(rule.ID) || rule.Command == "" || rule.Pattern == "" || rule.Replacement == "" || rule.Cause == "" {
			return fmt.Errorf("invalid rule %q", rule.ID)
		}
		if _, ok := seen[rule.ID]; ok {
			return fmt.Errorf("duplicate rule %q", rule.ID)
		}
		seen[rule.ID] = struct{}{}
		pattern, err := regexp.Compile(rule.Pattern)
		if err != nil {
			return fmt.Errorf("rule %q: %w", rule.ID, err)
		}
		if err := validateTransformationTemplate(rule.Replacement, pattern.NumSubexp()); err != nil {
			return fmt.Errorf("rule %q: %w", rule.ID, err)
		}
		if err := validateExplanationTemplate(rule.Cause, pattern.NumSubexp()); err != nil {
			return fmt.Errorf("rule %q: %w", rule.ID, err)
		}
		if rule.Risk != diagnose.RiskSafe && rule.Risk != diagnose.RiskHigh && rule.Risk != diagnose.RiskUnknown {
			return fmt.Errorf("rule %q has invalid risk", rule.ID)
		}
		if err := validateRiskMetadata(rule); err != nil {
			return fmt.Errorf("rule %q: %w", rule.ID, err)
		}
	}
	return nil
}

var identifierPattern = regexp.MustCompile(`^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`)
var semanticVersionPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:(?:0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:(?:0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$`)

func identifier(value string) bool { return identifierPattern.MatchString(value) }

func semanticVersion(value string) bool { return semanticVersionPattern.MatchString(value) }

func validateTransformationTemplate(template string, captures int) error {
	for index := 0; index < len(template); index++ {
		if template[index] != '$' {
			continue
		}
		if index+1 >= len(template) {
			return errors.New("transformation template ends with $")
		}
		if template[index+1] == '$' {
			index++
			continue
		}
		if template[index+1] < '1' || template[index+1] > '9' {
			return errors.New("transformation template only permits numeric capture references")
		}
		capture := 0
		for index+1 < len(template) && template[index+1] >= '0' && template[index+1] <= '9' {
			index++
			capture = capture*10 + int(template[index]-'0')
			if capture > captures {
				return fmt.Errorf("transformation template references unavailable capture $%d", capture)
			}
		}
	}
	return nil
}

func validateExplanationTemplate(template string, captures int) error {
	if len(template) > 512 || !utf8.ValidString(template) {
		return errors.New("explanation template exceeds limits")
	}
	for _, character := range template {
		if unicode.IsControl(character) {
			return errors.New("explanation template contains control characters")
		}
	}
	return validateTransformationTemplate(template, captures)
}

func validateRiskMetadata(rule Rule) error {
	if rule.RiskRationale == "" {
		return errors.New("risk rationale is required")
	}
	return validateExplanationTemplate(rule.RiskRationale, 0)
}
