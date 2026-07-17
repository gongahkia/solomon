package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
)

const CandidateCorpusSchemaVersionV1 = 1

type CommandCandidateCorpus struct {
	SchemaVersion int                `json:"schema_version"`
	Candidates    []CommandCandidate `json:"candidates"`
}

type CommandCandidate struct {
	ID          string `json:"id"`
	Command     string `json:"command"`
	Replacement string `json:"replacement"`
}

func LoadCommandCandidateCorpus(path string) (CommandCandidateCorpus, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return CommandCandidateCorpus{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var corpus CommandCandidateCorpus
	if err := decoder.Decode(&corpus); err != nil {
		return CommandCandidateCorpus{}, fmt.Errorf("parse command candidate corpus: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return CommandCandidateCorpus{}, errors.New("parse command candidate corpus: multiple JSON values")
		}
		return CommandCandidateCorpus{}, fmt.Errorf("parse command candidate corpus: trailing data: %w", err)
	}
	if err := corpus.Validate(); err != nil {
		return CommandCandidateCorpus{}, err
	}
	return corpus, nil
}

func (c CommandCandidateCorpus) Validate() error {
	if c.SchemaVersion != CandidateCorpusSchemaVersionV1 {
		return fmt.Errorf("unsupported command candidate corpus schema version %d", c.SchemaVersion)
	}
	if len(c.Candidates) == 0 {
		return errors.New("command candidate corpus must contain at least one candidate")
	}
	seen := map[string]struct{}{}
	for _, candidate := range c.Candidates {
		if !identifier(candidate.ID) || !identifier(candidate.Command) || !identifier(candidate.Replacement) || candidate.Command == candidate.Replacement {
			return fmt.Errorf("invalid command candidate %q", candidate.ID)
		}
		if _, exists := seen[candidate.ID]; exists {
			return fmt.Errorf("duplicate command candidate %q", candidate.ID)
		}
		seen[candidate.ID] = struct{}{}
	}
	return nil
}

func RunCommandCandidateCorpus(corpus CommandCandidateCorpus, resolve func(string) (string, bool)) error {
	if err := corpus.Validate(); err != nil {
		return err
	}
	if resolve == nil {
		return errors.New("missing command candidate resolver")
	}
	for _, candidate := range corpus.Candidates {
		actual, matched := resolve(candidate.Command)
		if !matched || actual != candidate.Replacement {
			return fmt.Errorf("command candidate %q resolved to %q, want %q", candidate.ID, actual, candidate.Replacement)
		}
	}
	return nil
}
