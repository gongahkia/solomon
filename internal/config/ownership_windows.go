//go:build windows

package config

import (
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

func ownedByCurrentUser(path string, _ os.FileInfo) bool {
	descriptor, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return false
	}
	owner, _, err := descriptor.Owner()
	if err != nil || owner == nil {
		return false
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil || user.User.Sid == nil {
		return false
	}
	return owner.Equals(user.User.Sid)
}

func hasSecurePermissions(path string, _ os.FileInfo, _ bool) bool {
	descriptor, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return false
	}
	dacl, _, err := descriptor.DACL()
	if err != nil || dacl == nil {
		return false
	}
	user, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil || user.User.Sid == nil {
		return false
	}
	administrators, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		return false
	}
	system, err := windows.CreateWellKnownSid(windows.WinLocalSystemSid)
	if err != nil {
		return false
	}
	for index := uint32(0); index < uint32(dacl.AceCount); index++ {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, index, &ace); err != nil {
			return false
		}
		if ace.Header.AceFlags&0x08 != 0 || ace.Header.AceType == windows.ACCESS_DENIED_ACE_TYPE {
			continue
		}
		if ace.Header.AceType != windows.ACCESS_ALLOWED_ACE_TYPE {
			return false
		}
		if ace.Mask&writeAccessMask == 0 {
			continue
		}
		sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart))
		if !sid.Equals(user.User.Sid) && !sid.Equals(administrators) && !sid.Equals(system) {
			return false
		}
	}
	return true
}

const writeAccessMask windows.ACCESS_MASK = windows.DELETE | windows.WRITE_DAC | windows.WRITE_OWNER | windows.GENERIC_ALL | windows.GENERIC_WRITE | windows.FILE_WRITE_DATA | windows.FILE_APPEND_DATA | windows.FILE_WRITE_EA | windows.FILE_WRITE_ATTRIBUTES
