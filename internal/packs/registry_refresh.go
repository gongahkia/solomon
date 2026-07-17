package packs

import (
	"errors"
	"fmt"
)

var ErrRegistryOffline = errors.New("registry is unavailable while offline")

type RegistryRefreshResult struct {
	Packs   []CompiledPack
	Updated bool
	Offline bool
}

func RefreshRegistry(state RegistryOptInState, cached []Pack, fetch func() ([]Pack, error)) (RegistryRefreshResult, error) {
	current, err := Resolve(cached)
	if err != nil {
		return RegistryRefreshResult{}, fmt.Errorf("resolve cached packs: %w", err)
	}
	if !state.Allowed() {
		return RegistryRefreshResult{Packs: current}, nil
	}
	if fetch == nil {
		return RegistryRefreshResult{Packs: current, Offline: true}, ErrRegistryOffline
	}
	available, err := fetch()
	if err != nil {
		return RegistryRefreshResult{Packs: current, Offline: true}, fmt.Errorf("%w: %w", ErrRegistryOffline, err)
	}
	updated, err := Resolve(available)
	if err != nil {
		return RegistryRefreshResult{Packs: current}, fmt.Errorf("resolve registry packs: %w", err)
	}
	return RegistryRefreshResult{Packs: updated, Updated: true}, nil
}
