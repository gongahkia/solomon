package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/gongahkia/close-enough/internal/diagnose"
)

type Pack struct {
	SchemaVersion int    `json:"schema_version"`
	ID            string `json:"id"`
	Version       string `json:"version"`
	Publisher     string `json:"publisher"`
	Rules         []Rule `json:"rules"`
}

type Rule struct {
	ID          string        `json:"id"`
	Command     string        `json:"command"`
	Pattern     string        `json:"pattern"`
	Replacement string        `json:"replacement"`
	Cause       string        `json:"cause"`
	Risk        diagnose.Risk `json:"risk"`
}

func Load(path string) (Pack, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Pack{}, err
	}
	var pack Pack
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&pack); err != nil {
		return Pack{}, fmt.Errorf("parse pack: %w", err)
	}
	return pack, nil
}

func (p Pack) Validate() error {
	if err := ValidateSchemaCompatibility(p.SchemaVersion); err != nil {
		return err
	}
	if !identifier(p.ID) || p.Version == "" || p.Publisher == "" {
		return errors.New("id, version, and publisher are required")
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
		if _, err := regexp.Compile(rule.Pattern); err != nil {
			return fmt.Errorf("rule %q: %w", rule.ID, err)
		}
		if rule.Risk != diagnose.RiskSafe && rule.Risk != diagnose.RiskHigh && rule.Risk != diagnose.RiskUnknown {
			return fmt.Errorf("rule %q has invalid risk", rule.ID)
		}
	}
	return nil
}

func identifier(value string) bool { return value != "" && !strings.ContainsAny(value, " \t/\\") }
