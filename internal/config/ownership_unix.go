//go:build unix

package config

import (
	"os"
	"syscall"
)

func ownedByCurrentUser(_ string, info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	return ok && int(stat.Uid) == os.Geteuid()
}

func hasSecurePermissions(_ string, info os.FileInfo, directory bool) bool {
	permissions := info.Mode().Perm()
	if directory {
		return permissions&0o022 == 0
	}
	return permissions&0o077 == 0
}
