package history

import (
	"context"
	"errors"
	"testing"
)

func TestDisabledRankerNeverAccessesStorage(t *testing.T) {
	store := &memoryStore{score: 9}
	ranker := New(false, store)
	if err := ranker.Record(context.Background(), "git status"); err != nil {
		t.Fatal(err)
	}
	if score, err := ranker.Score(context.Background(), "git"); err != nil || score != 0 {
		t.Fatalf("disabled score = %d, %v", score, err)
	}
	if store.recordCalls != 0 || store.scoreCalls != 0 {
		t.Fatalf("disabled ranker used storage: %#v", store)
	}
}

func TestEnabledRankerHashesCommandBeforeStorage(t *testing.T) {
	store := &memoryStore{score: 3}
	ranker := New(true, store)
	command := "git --token=secret status"
	if err := ranker.Record(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if store.recorded != Key(command) || store.recorded == command {
		t.Fatalf("unexpected stored value: %q", store.recorded)
	}
	if score, err := ranker.Score(context.Background(), "git"); err != nil || score != 3 || store.scored != Key("git") {
		t.Fatalf("unexpected score: %d, %v, %#v", score, err, store)
	}
}

func TestEnabledRankerRequiresStore(t *testing.T) {
	ranker := New(true, nil)
	if err := ranker.Record(context.Background(), "git"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("record error = %v", err)
	}
	if _, err := ranker.Score(context.Background(), "git"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("score error = %v", err)
	}
}

type memoryStore struct {
	recorded    string
	scored      string
	recordCalls int
	scoreCalls  int
	score       int
}

func (store *memoryStore) Record(_ context.Context, key string) error {
	store.recordCalls++
	store.recorded = key
	return nil
}

func (store *memoryStore) Score(_ context.Context, key string) (int, error) {
	store.scoreCalls++
	store.scored = key
	return store.score, nil
}
