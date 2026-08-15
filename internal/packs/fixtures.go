package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
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
	data, err := readUserAuthorizedFile(path)
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

func LoadFixtureCorpus(directory string) ([]Fixture, error) {
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	fixtures := make([]Fixture, 0, len(entries))
	seen := map[string]struct{}{}
	for _, entry := range entries {
		if filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			return nil, err
		}
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("fixture corpus entry %q is not a regular file", entry.Name())
		}
		fixture, err := LoadFixture(filepath.Join(directory, entry.Name()))
		if err != nil {
			return nil, fmt.Errorf("load fixture %q: %w", entry.Name(), err)
		}
		if err := fixture.Validate(); err != nil {
			return nil, fmt.Errorf("validate fixture %q: %w", entry.Name(), err)
		}
		for _, test := range fixture.Cases {
			if _, exists := seen[test.ID]; exists {
				return nil, fmt.Errorf("duplicate fixture case %q", test.ID)
			}
			seen[test.ID] = struct{}{}
		}
		fixtures = append(fixtures, fixture)
	}
	if len(fixtures) == 0 {
		return nil, errors.New("fixture corpus must contain at least one JSON fixture")
	}
	return fixtures, nil
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
	return RunFixtureCorpus(pack, []Fixture{fixture})
}

func RunFixtureCorpus(pack Pack, fixtures []Fixture) error {
	if len(fixtures) == 0 {
		return errors.New("fixture corpus must contain at least one fixture")
	}
	compiled, err := Compile(pack)
	if err != nil {
		return err
	}
	seen := map[string]struct{}{}
	for _, fixture := range fixtures {
		if err := fixture.Validate(); err != nil {
			return err
		}
		for _, test := range fixture.Cases {
			if _, exists := seen[test.ID]; exists {
				return fmt.Errorf("duplicate fixture case %q", test.ID)
			}
			seen[test.ID] = struct{}{}
			rule, matched := compiled.Match(test.Command, test.Input)
			actual := ""
			if matched {
				actual = rule.ID
			}
			if actual != test.RuleID {
				return fmt.Errorf("fixture case %q matched %q, want %q", test.ID, actual, test.RuleID)
			}
		}
	}
	return nil
}
