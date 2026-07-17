package packs

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/gongahkia/close-enough/internal/securetemp"
)

type State struct {
	Enabled []string `json:"enabled"`
}

func LoadState(path string) (State, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return State{}, nil
	}
	if err != nil {
		return State{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var state State
	if err := decoder.Decode(&state); err != nil {
		return State{}, fmt.Errorf("parse pack state: %w", err)
	}
	if err := state.Validate(); err != nil {
		return State{}, err
	}
	return state, nil
}

func (s *State) Enable(id string) bool {
	if !identifier(id) || s.EnabledFor(id) {
		return false
	}
	s.Enabled = append(s.Enabled, id)
	sort.Strings(s.Enabled)
	return true
}

func (s *State) Disable(id string) bool {
	for index, enabled := range s.Enabled {
		if enabled == id {
			s.Enabled = append(s.Enabled[:index], s.Enabled[index+1:]...)
			return true
		}
	}
	return false
}

func (s State) EnabledFor(id string) bool {
	return sort.SearchStrings(s.Enabled, id) < len(s.Enabled) && s.Enabled[sort.SearchStrings(s.Enabled, id)] == id
}

func (s State) Validate() error {
	previous := ""
	for _, id := range s.Enabled {
		if !identifier(id) || id <= previous {
			return errors.New("enabled pack ids must be unique lowercase kebab identifiers")
		}
		previous = id
	}
	return nil
}

func WriteState(path string, state State) (result error) {
	if err := state.Validate(); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	temporary, err := securetemp.Create(filepath.Dir(path), "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	defer func() { result = errors.Join(result, temporary.Cleanup()) }()
	if _, err := temporary.Write(data); err != nil {
		return err
	}
	return temporary.Commit(path)
}
