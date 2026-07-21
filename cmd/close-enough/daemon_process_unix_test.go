//go:build !windows

package main

import (
	"os/exec"
	"testing"
)

func TestDetachDaemonProcessCreatesSession(t *testing.T) {
	command := exec.Command("true")
	detachDaemonProcess(command)
	if command.SysProcAttr == nil || !command.SysProcAttr.Setsid {
		t.Fatalf("daemon process attributes = %#v", command.SysProcAttr)
	}
}
