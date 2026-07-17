package filesystem

import "testing"

func TestSupportedPlatformsExposeRequiredCapabilities(t *testing.T) {
	for _, platform := range []string{"darwin", "linux", "windows"} {
		t.Run(platform, func(t *testing.T) {
			capabilities := For(platform)
			for _, capability := range []Capability{AtomicReplace, RestrictivePermissions, OwnerVerification} {
				if !capabilities.Supports(capability) {
					t.Fatalf("%s does not support %s", platform, capability)
				}
			}
		})
	}
}

func TestUnknownPlatformFailsClosed(t *testing.T) {
	capabilities := For("unknown")
	if capabilities.Supports(AtomicReplace) || capabilities.Require(AtomicReplace) == nil {
		t.Fatalf("unexpected capabilities: %#v", capabilities)
	}
}
