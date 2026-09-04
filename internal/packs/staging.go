package packs

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/gongahkia/solomon/internal/securetemp"
)

type StagedDownload struct {
	temporary *securetemp.File
	Size      int64
}

func StageDownload(directory string, source io.Reader) (*StagedDownload, error) {
	temporary, err := securetemp.Create(directory, ".pack-stage-*")
	if err != nil {
		return nil, err
	}
	size, err := io.Copy(temporary, source)
	if err != nil {
		_ = temporary.Cleanup()
		return nil, err
	}
	return &StagedDownload{temporary: temporary, Size: size}, nil
}

func (s *StagedDownload) Path() string { return s.temporary.Path() }

func (s *StagedDownload) Commit(destination string) error { return s.temporary.Commit(destination) }

func (s *StagedDownload) Discard() error { return s.temporary.Cleanup() }

func ActivateStagedPack(staged *StagedDownload, directory string) (string, error) {
	return activateStagedPack(staged, directory, verifyActivatedPack)
}

func activateStagedPack(staged *StagedDownload, directory string, verify func(string, []byte) error) (string, error) {
	if staged == nil {
		return "", errors.New("missing staged pack")
	}
	data, err := readUserAuthorizedFile(staged.Path())
	if err != nil {
		return "", err
	}
	pack, err := decodePack(data)
	if err != nil {
		return "", err
	}
	if _, err := Compile(pack); err != nil {
		return "", err
	}
	target := filepath.Join(directory, pack.ID+"-"+pack.Version+".json")
	backup, err := stageActivationBackup(directory, target)
	if err != nil {
		return "", err
	}
	if backup != nil {
		defer backup.Cleanup()
	}
	if err := staged.Commit(target); err != nil {
		return "", err
	}
	if err := verify(target, data); err != nil {
		if rollbackErr := rollbackActivation(target, backup); rollbackErr != nil {
			return "", fmt.Errorf("activation verification failed: %w; rollback failed: %v", err, rollbackErr)
		}
		return "", fmt.Errorf("activation verification failed: %w", err)
	}
	return target, nil
}

func stageActivationBackup(directory, target string) (*securetemp.File, error) {
	info, err := os.Lstat(target)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, fmt.Errorf("activation target %q is not a regular file", target)
	}
	data, err := readUserAuthorizedFile(target)
	if err != nil {
		return nil, err
	}
	backup, err := securetemp.Create(directory, ".pack-rollback-*")
	if err != nil {
		return nil, err
	}
	if written, err := backup.Write(data); err != nil || written != len(data) {
		_ = backup.Cleanup()
		if err != nil {
			return nil, err
		}
		return nil, io.ErrShortWrite
	}
	return backup, nil
}

func verifyActivatedPack(target string, expected []byte) error {
	data, err := readUserAuthorizedFile(target)
	if err != nil {
		return err
	}
	if !bytes.Equal(data, expected) {
		return errors.New("activated pack differs from staged pack")
	}
	pack, err := decodePack(data)
	if err != nil {
		return err
	}
	_, err = Compile(pack)
	return err
}

func rollbackActivation(target string, backup *securetemp.File) error {
	if backup != nil {
		return backup.Commit(target)
	}
	info, err := os.Lstat(target)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("activation target %q is not a regular file", target)
	}
	return os.Remove(target)
}
