package credential

import (
	"context"
	"crypto/rand"
	"errors"
)

var ErrDisabled = errors.New("credential store is disabled")
var ErrUnavailable = errors.New("OS credential store is unavailable")
var ErrNotFound = errors.New("credential not found")

const HistoryKeySize = 32

type Store interface {
	Load(context.Context, string, string) ([]byte, error)
	Save(context.Context, string, string, []byte) error
	Delete(context.Context, string, string) error
}

type HistoryKeys struct {
	enabled bool
	store   Store
}

func NewHistoryKeys(enabled bool, store Store) HistoryKeys {
	return HistoryKeys{enabled: enabled, store: store}
}

func (keys HistoryKeys) Load(ctx context.Context, scope string) ([]byte, error) {
	if !keys.enabled {
		return nil, ErrDisabled
	}
	if keys.store == nil {
		return nil, ErrUnavailable
	}
	if !validScope(scope) {
		return nil, errors.New("invalid history key scope")
	}
	key, err := keys.store.Load(ctx, "close-enough/history", scope)
	if err != nil {
		return nil, err
	}
	if len(key) != HistoryKeySize {
		return nil, errors.New("invalid history key length")
	}
	return append([]byte(nil), key...), nil
}

func (keys HistoryKeys) Generate() ([]byte, error) {
	if !keys.enabled {
		return nil, ErrDisabled
	}
	if keys.store == nil {
		return nil, ErrUnavailable
	}
	key := make([]byte, HistoryKeySize)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	return key, nil
}

func (keys HistoryKeys) Save(ctx context.Context, scope string, key []byte) error {
	if !keys.enabled {
		return ErrDisabled
	}
	if keys.store == nil {
		return ErrUnavailable
	}
	if !validScope(scope) {
		return errors.New("invalid history key scope")
	}
	if len(key) != HistoryKeySize {
		return errors.New("invalid history key length")
	}
	return keys.store.Save(ctx, "close-enough/history", scope, append([]byte(nil), key...))
}

func (keys HistoryKeys) Delete(ctx context.Context, scope string) error {
	if !keys.enabled {
		return ErrDisabled
	}
	if keys.store == nil {
		return ErrUnavailable
	}
	if !validScope(scope) {
		return errors.New("invalid history key scope")
	}
	return keys.store.Delete(ctx, "close-enough/history", scope)
}

func validScope(scope string) bool {
	if scope == "" || len(scope) > 128 {
		return false
	}
	for _, character := range scope {
		if character >= 'a' && character <= 'z' || character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || character == '.' || character == '_' || character == '-' {
			continue
		}
		return false
	}
	return true
}
