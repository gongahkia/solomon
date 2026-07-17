package history

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

var ErrUnavailable = errors.New("history store is unavailable")

type Store interface {
	Record(context.Context, string) error
	Score(context.Context, string) (int, error)
}

type Ranker struct {
	enabled bool
	store   Store
}

func New(enabled bool, store Store) Ranker {
	return Ranker{enabled: enabled, store: store}
}

func (ranker Ranker) Record(ctx context.Context, command string) error {
	if !ranker.enabled {
		return nil
	}
	if ranker.store == nil {
		return ErrUnavailable
	}
	return ranker.store.Record(ctx, Key(command))
}

func (ranker Ranker) Score(ctx context.Context, candidate string) (int, error) {
	if !ranker.enabled {
		return 0, nil
	}
	if ranker.store == nil {
		return 0, ErrUnavailable
	}
	return ranker.store.Score(ctx, Key(candidate))
}

func Key(command string) string {
	digest := sha256.Sum256([]byte(command))
	return hex.EncodeToString(digest[:])
}
