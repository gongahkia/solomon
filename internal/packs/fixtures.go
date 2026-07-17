package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
)

const FixtureSchemaVersionV1 = 1

type Fixture struct {
	SchemaVersion int           `json:"schema_version"`
	Cases         []FixtureCase `json:"cases"`
}

type FixtureCase struct {
	ID      string `json:"id"`
	Command string `json:"command"`
	Input   string `json:"input"`
	RuleID  string `json:"rule_id,omitempty"`
}

func LoadFixture(path string) (Fixture, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Fixture{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var fixture Fixture
	if err := decoder.Decode(&fixture); err != nil {
		return Fixture{}, fmt.Errorf("parse fixture: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return Fixture{}, errors.New("parse fixture: multiple JSON values")
	}
	return fixture, nil
}

func (f Fixture) Validate() error {
	if f.SchemaVersion != FixtureSchemaVersionV1 {
		return fmt.Errorf("unsupported fixture schema version %d", f.SchemaVersion)
	}
	if len(f.Cases) == 0 {
		return errors.New("fixture must contain at least one case")
	}
	seen := map[string]struct{}{}
	for _, fixture := range f.Cases {
		if !identifier(fixture.ID) || fixture.Command == "" {
			return fmt.Errorf("invalid fixture case %q", fixture.ID)
		}
		if _, exists := seen[fixture.ID]; exists {
			return fmt.Errorf("duplicate fixture case %q", fixture.ID)
		}
		seen[fixture.ID] = struct{}{}
	}
	return nil
}

func RunFixture(pack Pack, fixture Fixture) error {
	if err := fixture.Validate(); err != nil {
		return err
	}
	compiled, err := Compile(pack)
	if err != nil {
		return err
	}
	for _, fixture := range fixture.Cases {
		rule, matched := compiled.Match(fixture.Command, fixture.Input)
		actual := ""
		if matched {
			actual = rule.ID
		}
		if actual != fixture.RuleID {
			return fmt.Errorf("fixture case %q matched %q, want %q", fixture.ID, actual, fixture.RuleID)
		}
	}
	return nil
}
