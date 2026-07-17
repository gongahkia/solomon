package packs

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/gongahkia/close-enough/internal/securetemp"
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
	if staged == nil {
		return "", errors.New("missing staged pack")
	}
	data, err := os.ReadFile(staged.Path())
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
	if info, err := os.Lstat(target); err == nil && !info.Mode().IsRegular() {
		return "", fmt.Errorf("activation target %q is not a regular file", target)
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if err := staged.Commit(target); err != nil {
		return "", err
	}
	return target, nil
}
