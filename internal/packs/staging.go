package packs

import (
	"io"

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
