//go:build unix

package config

import (
	"os"
	"syscall"
	"testing"
	"time"
)

func TestOwnedByCurrentUserRejectsDifferentOwner(t *testing.T) {
	info := testFileInfo{mode: 0o600, sys: &syscall.Stat_t{Uid: uint32(os.Geteuid() + 1)}}
	if ownedByCurrentUser("ignored", info) {
		t.Fatal("expected foreign owner to be rejected")
	}
}

type testFileInfo struct {
	mode os.FileMode
	sys  any
}

func (info testFileInfo) Name() string       { return "trusted" }
func (info testFileInfo) Size() int64        { return 0 }
func (info testFileInfo) Mode() os.FileMode  { return info.mode }
func (info testFileInfo) ModTime() time.Time { return time.Time{} }
func (info testFileInfo) IsDir() bool        { return info.mode.IsDir() }
func (info testFileInfo) Sys() any           { return info.sys }
