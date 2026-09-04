package packs

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/gongahkia/solomon/internal/securetemp"
)

type PublisherKey struct {
	ID        string `json:"id"`
	PublicKey string `json:"public_key"`
}

type Keyring struct {
	Publishers []PublisherKey `json:"publishers"`
	Revoked    []string       `json:"revoked,omitempty"`
}

func LoadKeyring(path string) (Keyring, error) {
	data, err := readUserAuthorizedFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return Keyring{}, nil
	}
	if err != nil {
		return Keyring{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var keyring Keyring
	if err := decoder.Decode(&keyring); err != nil {
		return Keyring{}, fmt.Errorf("parse keyring: %w", err)
	}
	if err := keyring.Validate(); err != nil {
		return Keyring{}, err
	}
	return keyring, nil
}

func (k Keyring) PublicKey(id string) (ed25519.PublicKey, bool) {
	if k.RevokedFor(id) {
		return nil, false
	}
	index := sort.Search(len(k.Publishers), func(index int) bool { return k.Publishers[index].ID >= id })
	if index == len(k.Publishers) || k.Publishers[index].ID != id {
		return nil, false
	}
	key, err := base64.RawStdEncoding.DecodeString(k.Publishers[index].PublicKey)
	return ed25519.PublicKey(key), err == nil
}

func ParsePublisherPublicKey(value string) (ed25519.PublicKey, error) {
	key, err := base64.RawStdEncoding.DecodeString(value)
	if err != nil || len(key) != ed25519.PublicKeySize {
		return nil, errors.New("invalid publisher public key")
	}
	return ed25519.PublicKey(key), nil
}

func (k *Keyring) Revoke(id string) bool {
	if !identifier(id) || k.RevokedFor(id) {
		return false
	}
	k.Revoked = append(k.Revoked, id)
	sort.Strings(k.Revoked)
	return true
}

func (k Keyring) RevokedFor(id string) bool {
	for _, revoked := range k.Revoked {
		if revoked == id {
			return true
		}
	}
	return false
}

func (k *Keyring) Add(id string, key ed25519.PublicKey) error {
	if !identifier(id) || len(key) != ed25519.PublicKeySize {
		return errors.New("invalid publisher key")
	}
	for _, publisher := range k.Publishers {
		if publisher.ID == id {
			return fmt.Errorf("publisher %q already exists", id)
		}
	}
	k.Publishers = append(k.Publishers, PublisherKey{ID: id, PublicKey: base64.RawStdEncoding.EncodeToString(key)})
	sort.Slice(k.Publishers, func(left, right int) bool { return k.Publishers[left].ID < k.Publishers[right].ID })
	return nil
}

func (k *Keyring) Remove(id string) bool {
	for index, publisher := range k.Publishers {
		if publisher.ID == id {
			k.Publishers = append(k.Publishers[:index], k.Publishers[index+1:]...)
			return true
		}
	}
	return false
}

func (k Keyring) Validate() error {
	previous := ""
	for _, publisher := range k.Publishers {
		key, err := base64.RawStdEncoding.DecodeString(publisher.PublicKey)
		if !identifier(publisher.ID) || publisher.ID <= previous || err != nil || len(key) != ed25519.PublicKeySize {
			return errors.New("invalid publisher keyring")
		}
		previous = publisher.ID
	}
	previous = ""
	for _, id := range k.Revoked {
		if !identifier(id) || id <= previous {
			return errors.New("invalid publisher revocations")
		}
		previous = id
	}
	return nil
}

func WriteKeyring(path string, keyring Keyring) (result error) {
	if err := keyring.Validate(); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	data, err := json.MarshalIndent(keyring, "", "  ")
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
