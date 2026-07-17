//go:build !unix && !windows

package config

import "os"

func ownedByCurrentUser(_ string, _ os.FileInfo) bool { return false }

func hasSecurePermissions(_ string, _ os.FileInfo, _ bool) bool { return false }
