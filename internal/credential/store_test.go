package credential

import (
	"context"
	"errors"
	"testing"
)

func TestHistoryKeysAreOptInAndValidated(t *testing.T) {
	store := &memoryStore{value: make([]byte, HistoryKeySize)}
	disabled := NewHistoryKeys(false, store)
	if _, err := disabled.Load(context.Background(), "project"); !errors.Is(err, ErrDisabled) {
		t.Fatalf("disabled load error = %v", err)
	}
	keys := NewHistoryKeys(true, store)
	if _, err := keys.Load(context.Background(), "project/unsafe"); err == nil {
		t.Fatal("expected invalid scope error")
	}
	if _, err := NewHistoryKeys(true, nil).Load(context.Background(), "project"); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("unavailable load error = %v", err)
	}
}

func TestHistoryKeysLoadAndSaveCopiesKeyMaterial(t *testing.T) {
	store := &memoryStore{value: make([]byte, HistoryKeySize)}
	store.value[0] = 1
	keys := NewHistoryKeys(true, store)
	loaded, err := keys.Load(context.Background(), "project")
	if err != nil {
		t.Fatal(err)
	}
	loaded[0] = 2
	if store.value[0] != 1 {
		t.Fatal("load exposed backend key memory")
	}
	key, err := keys.Generate()
	if err != nil {
		t.Fatal(err)
	}
	if len(key) != HistoryKeySize {
		t.Fatalf("key length = %d", len(key))
	}
	if err := keys.Save(context.Background(), "project", key); err != nil {
		t.Fatal(err)
	}
	key[0] ^= 0xff
	if store.value[0] == key[0] {
		t.Fatal("save exposed caller key memory")
	}
	if err := keys.Delete(context.Background(), "project"); err != nil {
		t.Fatal(err)
	}
}

func TestHistoryKeysRejectMalformedStoredKey(t *testing.T) {
	keys := NewHistoryKeys(true, &memoryStore{value: []byte("short")})
	if _, err := keys.Load(context.Background(), "project"); err == nil {
		t.Fatal("expected malformed key error")
	}
}

type memoryStore struct {
	value []byte
}

func (store *memoryStore) Load(context.Context, string, string) ([]byte, error) {
	return append([]byte(nil), store.value...), nil
}

func (store *memoryStore) Save(_ context.Context, _ string, _ string, value []byte) error {
	store.value = append([]byte(nil), value...)
	return nil
}

func (store *memoryStore) Delete(context.Context, string, string) error {
	store.value = nil
	return nil
}
