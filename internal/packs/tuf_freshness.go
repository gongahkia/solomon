package packs

import (
	"errors"
	"fmt"
	"time"
)

type RegistryState struct{ Versions map[string]int }

func (s *RegistryState) Accept(role string, version int, expires string, now time.Time) error {
	if version < 1 {
		return errors.New("invalid metadata version")
	}
	deadline, err := time.Parse(time.RFC3339, expires)
	if err != nil || !now.Before(deadline) {
		return errors.New("registry metadata is expired")
	}
	if s != nil {
		if s.Versions == nil {
			s.Versions = map[string]int{}
		}
		if version < s.Versions[role] {
			return fmt.Errorf("registry metadata rollback for %s", role)
		}
		s.Versions[role] = version
	}
	return nil
}
