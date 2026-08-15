package securetemp

import (
	"errors"
	"os"

	"github.com/gongahkia/close-enough/internal/filesystem"
)

type File struct {
	file      *os.File
	path      string
	closed    bool
	committed bool
}

func Create(dir, pattern string) (*File, error) {
	file, err := os.CreateTemp(dir, pattern)
	if err != nil {
		return nil, err
	}
	if err := file.Chmod(0o600); err != nil {
		path := file.Name()
		_ = file.Close()
		// #nosec G703 -- path is the just-created temporary file returned by os.CreateTemp.
		_ = os.Remove(path)
		return nil, err
	}
	return &File{file: file, path: file.Name()}, nil
}

func (file *File) Path() string { return file.path }

func (file *File) Write(data []byte) (int, error) {
	if file.closed {
		return 0, os.ErrClosed
	}
	return file.file.Write(data)
}

func (file *File) Commit(path string) error {
	if err := filesystem.Current().Require(filesystem.AtomicReplace); err != nil {
		return err
	}
	if file.committed {
		return errors.New("temporary file already committed")
	}
	if !file.closed {
		if err := file.file.Sync(); err != nil {
			return err
		}
		if err := file.file.Close(); err != nil {
			return err
		}
		file.closed = true
	}
	if err := os.Rename(file.path, path); err != nil {
		return err
	}
	file.committed = true
	return nil
}

func (file *File) Cleanup() error {
	var result error
	if !file.closed {
		result = file.file.Close()
		file.closed = true
	}
	if !file.committed {
		if err := os.Remove(file.path); err != nil && !errors.Is(err, os.ErrNotExist) && result == nil {
			result = err
		}
	}
	return result
}
