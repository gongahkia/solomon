package filesystem

import (
	"fmt"
	"runtime"
)

type Capability string

const (
	AtomicReplace          Capability = "atomic-replace"
	RestrictivePermissions Capability = "restrictive-permissions"
	OwnerVerification      Capability = "owner-verification"
)

type Capabilities struct {
	Platform               string `json:"platform"`
	AtomicReplace          bool   `json:"atomic_replace"`
	RestrictivePermissions bool   `json:"restrictive_permissions"`
	OwnerVerification      bool   `json:"owner_verification"`
}

func Current() Capabilities { return For(runtime.GOOS) }

func For(platform string) Capabilities {
	capabilities := Capabilities{Platform: platform}
	switch platform {
	case "aix", "darwin", "dragonfly", "freebsd", "illumos", "ios", "linux", "netbsd", "openbsd", "solaris", "windows":
		capabilities.AtomicReplace = true
		capabilities.RestrictivePermissions = true
		capabilities.OwnerVerification = true
	}
	return capabilities
}

func (capabilities Capabilities) Supports(capability Capability) bool {
	switch capability {
	case AtomicReplace:
		return capabilities.AtomicReplace
	case RestrictivePermissions:
		return capabilities.RestrictivePermissions
	case OwnerVerification:
		return capabilities.OwnerVerification
	default:
		return false
	}
}

func (capabilities Capabilities) Require(capability Capability) error {
	if capabilities.Supports(capability) {
		return nil
	}
	return fmt.Errorf("filesystem capability unavailable: %s", capability)
}
